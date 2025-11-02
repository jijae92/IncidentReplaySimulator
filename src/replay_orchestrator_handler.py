import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from athena import AthenaClient
from config import get_config
from s3 import S3Client


logger = Logger(service="replay_orchestrator")


def _pick(d: Dict[str, Any], *names: str):
    for name in names:
        value = d.get(name)
        if value not in (None, "", "null"):
            return value
    return None


def _as_epoch_ms(value: Any) -> int:
    if isinstance(value, (int, float)):
        numeric = float(value)
        return int(numeric if numeric >= 1e12 else numeric * 1000)

    string_value = str(value).strip()
    if string_value.isdigit():
        numeric = int(string_value)
        return numeric if numeric >= 1_000_000_000_000 else numeric * 1000

    parsed = datetime.fromisoformat(string_value.replace("Z", "+00:00"))
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _missing(keys: Iterable[str], getter) -> list[str]:
    missing = []
    for key in keys:
        try:
            current = getter(key)
        except Exception:  # noqa: BLE001 - treat lookup errors as missing
            current = None
        if current in (None, "", "null"):
            missing.append(key)
    return missing


def _to_iso8601(ms: int) -> str:
    return (
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


REQUIRED_EVT_BASE = ("metadata_key", "region")
REQUIRED_EVT_TIME = ("from", "to")


def lambda_handler(event: dict, context: LambdaContext) -> dict:  # noqa: ARG001 - context provided by Lambda
    logger.info(f"Received event: {event}")

    event = event or {}

    allow_default = os.getenv("ALLOW_DEFAULT_TIMEWINDOW", "").lower() in ("1", "true", "yes")

    metadata_key = _pick(event, "metadata_key", "metadataKey")
    region = _pick(event, "region", "awsRegion")
    replay_inputs_prefix = _pick(event, "replay_inputs_prefix", "replayInputsPrefix")

    if not region:
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-northeast-2"

    if not metadata_key:
        prefix = os.getenv("ATHENA_OUTPUT_PREFIX") or "athena/results/"
        metadata_key = f"{prefix}{uuid.uuid4()}/metadata.json"

    raw_from = _pick(event, "from", "time_from", "start", "startTime", "timeFrom")
    raw_to = _pick(event, "to", "time_to", "end", "endTime", "timeTo")

    if raw_from and raw_to:
        try:
            evt_from_ms = _as_epoch_ms(raw_from)
            evt_to_ms = _as_epoch_ms(raw_to)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Invalid time window format | from=%r to=%r | error=%s",
                raw_from,
                raw_to,
                exc,
            )
            raise ValueError("Invalid time range format") from exc
    else:
        if not allow_default:
            missing = [key for key, value in {"from": raw_from, "to": raw_to}.items() if not value]
            logger.error(
                "Missing event keys: %s | event=%s",
                missing,
                {
                    "metadata_key": event.get("metadata_key"),
                    "metadataKey": event.get("metadataKey"),
                    "region": event.get("region"),
                    "awsRegion": event.get("awsRegion"),
                    "from": raw_from,
                    "to": raw_to,
                },
            )
            raise ValueError("Missing required configuration or event parameters.")
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        evt_to_ms = now_ms
        evt_from_ms = now_ms - 3600 * 1000

    config = get_config()
    required_config_keys = (
        "athena_work_group_name",
        "athena_output_location",
        "glue_database_name",
        "bucket_replay",
        "athena_results_bucket",
    )
    config_missing = _missing(required_config_keys, lambda key: getattr(config, key))
    if config_missing:
        logger.error("Missing configuration keys: %s", config_missing)
        raise ValueError("Missing required configuration or event parameters.")

    athena_client = AthenaClient(region=config.aws_region)
    s3_client = S3Client(region=config.aws_region)

    evt_from_iso = _to_iso8601(evt_from_ms)
    evt_to_iso = _to_iso8601(evt_to_ms)

    normalized_event = {
        "metadata_key": metadata_key,
        "region": region,
        "replay_inputs_prefix": replay_inputs_prefix,
        "from_ms": evt_from_ms,
        "to_ms": evt_to_ms,
        "from_iso": evt_from_iso,
        "to_iso": evt_to_iso,
    }
    logger.debug(f"Normalized event context: {normalized_event}")

    query_file_key = "sql/queries/createuser_sequence.sql"
    try:
        sql_query = s3_client.get_object(
            bucket_name=config.bucket_replay,
            key=query_file_key,
        )
    except Exception as exc:  # noqa: BLE001 - propagate for Lambda to surface
        logger.error("Failed to retrieve Athena query from S3: %s", exc)
        raise

    query_params = {
        "from_ts": evt_from_iso,
        "to_ts": evt_to_iso,
    }

    logger.info(f"Starting Athena query with params: {query_params}")
    query_execution_id = athena_client.start_query(
        sql=sql_query,
        params=query_params,
        workgroup=config.athena_work_group_name,
        output_s3=config.athena_output_location,
        database=config.glue_database_name,
    )
    logger.info(f"Athena query started with ID: {query_execution_id}")

    try:
        query_execution = athena_client.wait_query(query_execution_id)
        status = query_execution["Status"]["State"]
        logger.info(f"Athena query {query_execution_id} finished with status: {status}")

        if status == "SUCCEEDED":
            results = athena_client.fetch_results(query_execution_id)
            logger.info(f"Fetched {len(results)} rows from Athena query.")

            output_key_prefix = f"irs/queries/{query_execution_id}"

            json_output_key = f"{output_key_prefix}.json"
            s3_client.put_object(
                bucket_name=config.athena_results_bucket,
                key=json_output_key,
                body=json.dumps(results, indent=2),
            )
            logger.info(
                "Results saved to s3://%s/%s",
                config.athena_results_bucket,
                json_output_key,
            )

            csv_output_key = None
            if results:
                import csv
                from io import StringIO

                csv_buffer = StringIO()
                fieldnames = list(results[0].keys())
                writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(results)
                csv_output_key = f"{output_key_prefix}.csv"
                s3_client.put_object(
                    bucket_name=config.athena_results_bucket,
                    key=csv_output_key,
                    body=csv_buffer.getvalue(),
                )
                logger.info(
                    "Results saved to s3://%s/%s",
                    config.athena_results_bucket,
                    csv_output_key,
                )

            total_count = len(results)
            unique_actors = len({row.get("actor_arn") for row in results if row.get("actor_arn")})
            unique_src_ips = len({row.get("src_ip") for row in results if row.get("src_ip")})

            summary_stats = {
                "total_matches": total_count,
                "unique_actors": unique_actors,
                "unique_src_ips": unique_src_ips,
                "query_execution_id": query_execution_id,
                "result_s3_json": f"s3://{config.athena_results_bucket}/{json_output_key}",
                "metadata_key": metadata_key,
                "region": region,
            }
            if csv_output_key:
                summary_stats["result_s3_csv"] = f"s3://{config.athena_results_bucket}/{csv_output_key}"

            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": "Athena query executed and results processed successfully",
                        "summary": summary_stats,
                    }
                ),
            }

        error_message = query_execution["Status"].get("StateChangeReason", "Unknown error")
        logger.error(f"Athena query failed: {error_message}")
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Athena query failed", "error": error_message}),
        }

    except TimeoutError as exc:
        logger.error(f"Athena query timed out: {exc}")
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Athena query timed out", "error": str(exc)}),
        }
    except Exception as exc:  # noqa: BLE001 - capture unexpected errors for observability
        logger.error(f"An unexpected error occurred during Athena query orchestration: {exc}")
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "An unexpected error occurred", "error": str(exc)}),
        }
