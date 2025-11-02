# src/reporter/handler.py

import csv
import json
import os
from datetime import datetime
from io import StringIO
from typing import Any, Dict
from urllib.parse import urlparse

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

try:  # pragma: no cover - lambda runtime imports
    from s3 import S3Client
except ImportError:  # pragma: no cover
    from .s3 import S3Client

try:  # pragma: no cover - lambda runtime imports
    from config import get_config
except ImportError:  # pragma: no cover
    from .config import get_config

try:  # pragma: no cover - lambda runtime imports
    from sns import SnsClient
except ImportError:  # pragma: no cover
    from .sns import SnsClient

logger = Logger(service="reporter")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    stripped = value.strip() if isinstance(value, str) else value
    if isinstance(stripped, str) and stripped == "":
        return default
    return stripped


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Parses an S3 URI into bucket name and key."""
    parsed_uri = urlparse(s3_uri)
    if parsed_uri.scheme != "s3":
        raise ValueError(f"Invalid S3 URI scheme: {s3_uri}")
    return parsed_uri.netloc, parsed_uri.path.lstrip("/")


def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    logger.info(f"Received event: {event}")

    config = get_config()
    sns_client = SnsClient(region=config.aws_region)
    s3_client = S3Client(region=config.aws_region)

    notify = bool(event.get("notify", False))
    summary_only = event.get("summary_only", False)

    # Resolve results bucket (event overrides environment)
    results_bucket_evt = event.get("results_bucket") or event.get("resultsBucket")
    results_bucket = (
        results_bucket_evt
        or _env("ATHENA_RESULTS_BUCKET")
        or config.athena_results_bucket
    )

    # Resolve metrics location
    metrics_s3_uri = event.get("metrics_s3_uri") or event.get("metrics_s3")
    if not metrics_s3_uri:
        metrics_key = event.get("metrics_key")
        if metrics_key and results_bucket:
            metrics_s3_uri = f"s3://{results_bucket}/{metrics_key}"
        else:
            logger.error("Missing metrics_s3_uri and cannot construct from (results_bucket, metrics_key).")
            raise ValueError("Missing required input or configuration.")

    # Resolve SNS topic ARN
    sns_arn_evt = event.get("notification_sns_arn") or event.get("notificationSnsArn")
    sns_arn = (
        sns_arn_evt
        or _env("NOTIFICATION_SNS_TOPIC_ARN")
        or config.notification_sns_topic_arn
    )
    if notify and not sns_arn:
        logger.error("notify=true but NOTIFICATION_SNS_TOPIC_ARN is missing.")
        raise ValueError("Missing required input or configuration.")

    logger.info(
        "CONFIG_RESOLVED %s",
        {
            "metrics_s3_uri": metrics_s3_uri,
            "results_bucket": results_bucket,
            "notify": notify,
            "sns_arn_present": bool(sns_arn),
        },
    )

    metrics_bucket, metrics_key = parse_s3_uri(metrics_s3_uri)
    metrics_json_body = s3_client.get_object(metrics_bucket, metrics_key)
    metrics = json.loads(metrics_json_body)
    logger.info(f"Loaded metrics: {metrics}")

    scenario = metrics.get("scenario", "Unknown Scenario")
    precision = metrics.get("precision", 0.0)
    recall = metrics.get("recall", 0.0)
    f1 = metrics.get("f1", 0.0)
    tp = metrics.get("tp", 0)
    fp = metrics.get("fp", 0)
    fn = metrics.get("fn", 0)

    summary_message = (
        f"Incident Replay Report for {scenario}:\n"
        f"  Precision: {precision:.2f}\n"
        f"  Recall: {recall:.2f}\n"
        f"  F1 Score: {f1:.2f}\n"
        f"  True Positives (TP): {tp}\n"
        f"  False Positives (FP): {fp}\n"
        f"  False Negatives (FN): {fn}\n"
        f"  Full report: {metrics_s3_uri}"
    )

    sns_message_id = None
    if notify:
        sns_response = sns_client.publish_message(
            topic_arn=sns_arn,
            message=summary_message,
            subject=f"Incident Replay Report - {scenario}",
        )
        sns_message_id = sns_response.get("MessageId")
        logger.info(f"Report published to SNS with MessageId: {sns_message_id}")

    artifact_prefix = None
    if not summary_only:
        scenario_name = (
            event.get("scenario_name")
            or event.get("scenarioName")
            or _env("SCENARIO_NAME")
            or "Unknown_Scenario"
        )
        scenario_slug = str(scenario_name).replace(" ", "_")
        output_timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        artifact_base_key = f"artifacts/{scenario_slug}_{output_timestamp}"
        logger.info(
            "ARTIFACT_PLAN %s",
            {
                "scenario_name": scenario_name,
                "artifact_json_key": f"{artifact_base_key}.json",
                "artifact_csv_key": f"{artifact_base_key}.csv",
            },
        )

        artifact_json_key = f"{artifact_base_key}.json"
        s3_client.put_object(
            bucket_name=config.athena_results_bucket,
            key=artifact_json_key,
            body=json.dumps(metrics, indent=2),
        )
        logger.info(f"Metrics JSON artifact saved to s3://{config.athena_results_bucket}/{artifact_json_key}")

        if metrics:
            csv_buffer = StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=metrics.keys())
            writer.writeheader()
            writer.writerow(metrics)
            artifact_csv_key = f"{artifact_base_key}.csv"
            s3_client.put_object(
                bucket_name=config.athena_results_bucket,
                key=artifact_csv_key,
                body=csv_buffer.getvalue(),
            )
            logger.info(f"Metrics CSV artifact saved to s3://{config.athena_results_bucket}/{artifact_csv_key}")

        artifact_prefix = f"s3://{config.athena_results_bucket}/{artifact_base_key}"

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "notified": bool(sns_message_id),
                "sns_message_id": sns_message_id,
                "artifact_prefix": artifact_prefix,
            }
        ),
    }
