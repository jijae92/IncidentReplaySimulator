from __future__ import annotations
"""Lambda entry point that seeds CloudTrail IAM replay events."""

import gzip
import io
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from aws_lambda_powertools import Logger, Tracer

from common.config import IRSConfig, load_config
from common.s3 import S3Client

logger = Logger(service="ingest_replay_log")
tracer = Tracer(service="ingest_replay_log")

_EVENT_SEQUENCE = ("CreateUser", "AttachUserPolicy", "CreateAccessKey")
_EVENT_SOURCE = "iam.amazonaws.com"


def _parse_start_time(start_time_str: str) -> datetime:  # pragma: no cover
    """Parse ISO8601 timestamp into UTC datetime."""
    try:
        parsed = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%SZ")
        return parsed.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("startTime must be in ISO8601 format YYYY-MM-DDTHH:MM:SSZ") from exc


def _cloudtrail_key(event_time: datetime, account_id: str, region: str, object_id: uuid.UUID) -> str:  # pragma: no cover
    """Render CloudTrail key with GUID and gzip suffix."""
    return (
        f"AWSLogs/{account_id}/CloudTrail/{region}/"
        f"{event_time:%Y/%m/%d}/"
        f"{account_id}_CloudTrail_{region}_{event_time:%Y%m%dT%H%M}Z_{object_id.hex}.json.gz"
    )


def _build_user_identity(account_id: str, actor_user: str) -> Dict[str, Any]:  # pragma: no cover
    """Construct a minimal CloudTrail userIdentity document."""
    return {
        "type": "IAMUser",
        "arn": f"arn:aws:iam::{account_id}:user/{actor_user}",
        "accountId": account_id,
        "userName": actor_user,
        "principalId": f"{account_id}:{actor_user}",
        "sessionContext": {
            "attributes": {
                "creationDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mfaAuthenticated": "false",
            }
        },
    }


def _build_event(
    event_name: str,
    event_time: datetime,
    account_id: str,
    region: str,
    actor_user: str,
    target_user: str,
    source_ip: str,
    user_agent: str,
) -> Dict[str, Any]:  # pragma: no cover
    """Create a CloudTrail record with required fields."""
    base = {
        "eventVersion": "1.08",
        "eventSource": _EVENT_SOURCE,
        "eventName": event_name,
        "awsRegion": region,
        "eventTime": event_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "userIdentity": _build_user_identity(account_id, actor_user),
        "sourceIPAddress": source_ip,
        "userAgent": user_agent,
        "requestParameters": json.dumps({}),
        "responseElements": json.dumps({}),
        "additionalEventData": {"AuthenticationMethod": "NoMFA"},
    }

    if event_name == "CreateUser":
        base["requestParameters"] = json.dumps({"userName": target_user})
        base["responseElements"] = json.dumps({
            "user": {
                "arn": f"arn:aws:iam::{account_id}:user/{target_user}",
                "userName": target_user,
                "userId": uuid.uuid4().hex[:16],
            }
        })
    elif event_name in {"AttachUserPolicy", "PutUserPolicy"}:
        base["requestParameters"] = json.dumps({
            "userName": target_user,
            "policyArn": "arn:aws:iam::aws:policy/AdministratorAccess",
        })
    elif event_name == "CreateAccessKey":
        base["responseElements"] = json.dumps({
            "accessKey": {
                "accessKeyId": f"AKIA{uuid.uuid4().hex[:16].upper()}",
                "status": "Active",
                "userName": target_user,
            }
        })

    return base


def _generate_records(
    event_time: datetime,
    account_id: str,
    region: str,
    actor_user: str,
    target_user: str,
) -> List[Dict[str, Any]]:  # pragma: no cover
    """Generate a CreateUser attack sequence CloudTrail Records array."""
    source_ip = f"203.0.113.{random.randint(1, 254)}"
    user_agent = "IRS-ReplaySimulator/1.0"
    records: List[Dict[str, Any]] = []
    current_time = event_time
    for name in _EVENT_SEQUENCE:
        records.append(                            _build_event(
                event_name=name,
                event_time=current_time,
                account_id=account_id,
                region=region,
                actor_user=actor_user,
                target_user=target_user,
                source_ip=source_ip,
                user_agent=user_agent,
            )
        )
        current_time += timedelta(minutes=2)
    return records


def _serialize_records(records: List[Dict[str, Any]]) -> bytes:  # pragma: no cover
    """Serialize and gzip CloudTrail records."""
    payload = json.dumps({"Records": records}, separators=(",", ":"), default=str).encode("utf-8")
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb") as gz:
        gz.write(payload)
    return buffer.getvalue()


@tracer.capture_lambda_handler
@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:  # pragma: no cover
    """
    Lambda handler for seeding replay events.

    Expects event:
    {
        "scenario": "iam_createuser",
        "count": 2,
        "startTime": "2025-01-01T00:00:00Z",
        "accountId": "123456789012",
        "region": "ap-northeast-2"
    }
    """
    if event.get("scenario") != "iam_createuser":
        raise ValueError("Unsupported scenario, expected 'iam_createuser'")

    config: IRSConfig = load_config()
    bucket_value = os.getenv("IRS_REPLAY_BUCKET", config.replay_bucket)
    if not bucket_value:
        raise EnvironmentError("IRS_REPLAY_BUCKET environment variable must be set")
    bucket = bucket_value

    count = max(1, int(event.get("count", 1)))
    start_time_str = event.get("startTime") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    base_time = _parse_start_time(start_time_str)
    account_id = event.get("accountId") or os.getenv("AWS_ACCOUNT_ID") or "000000000000"
    region = event.get("region") or os.getenv("AWS_REGION") or "us-east-1"

    s3_client = S3Client(config=config)
    objects: List[str] = []

    for index in range(count):
        event_time = base_time + timedelta(minutes=5 * index)
        actor_user = f"replay-actor-{index+1}"
        target_user = f"replay-target-{index+1}"
        records = _generate_records(event_time, account_id, region, actor_user, target_user)
        object_id = uuid.uuid4()
        key = _cloudtrail_key(event_time, account_id, region, object_id)
        compressed = _serialize_records(records)
        s3_client.put_bytes(bucket, key, compressed, "application/gzip")
        objects.append(f"s3://{bucket}/{key}")
        logger.info("Replay object stored", extra={"bucket": bucket, "key": key})

    return {
        "statusCode": 200,
        "body": {
            "objects": objects,
            "count": len(objects),
        },
    }


def _is_table_missing(reason: Optional[str]) -> bool:
    if not reason:
        return False
    normalized = reason.upper()
    return "TABLE_NOT_FOUND" in normalized or "DOES NOT EXIST" in normalized
