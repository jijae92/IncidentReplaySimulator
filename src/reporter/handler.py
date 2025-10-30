# src/reporter/handler.py

import json

import os

import csv

from io import StringIO

from datetime import datetime

from urllib.parse import urlparse



from aws_lambda_powertools import Logger

from aws_lambda_powertools.utilities.typing import LambdaContext



from src.common.sns import SnsClient



from src.common.s3 import S3Client



from src.common.schemas import ReportMetrics # Assuming ReportMetrics schema is defined



from src.common.config import NOTIFICATION_SNS_TOPIC_ARN, ATHENA_RESULTS_BUCKET, AWS_REGION



logger = Logger(service="reporter")

sns_client = SnsClient(region=AWS_REGION)

s3_client = S3Client(region=AWS_REGION)



def parse_s3_uri(s3_uri: str) -> tuple[str, str]:

    """Parses an S3 URI into bucket name and key."""

    parsed_uri = urlparse(s3_uri)

    if parsed_uri.scheme != "s3":

        raise ValueError(f"Invalid S3 URI scheme: {s3_uri}")

    bucket_name = parsed_uri.netloc

    key = parsed_uri.path.lstrip('/')

    return bucket_name, key



def lambda_handler(event: dict, context: LambdaContext) -> dict:

    logger.info(f"Received event: {event}")



    metrics_s3_uri = event.get("metrics_s3")

    summary_only = event.get("summary_only", False)



    if not all([metrics_s3_uri, NOTIFICATION_SNS_TOPIC_ARN, ATHENA_RESULTS_BUCKET]):

        logger.error("Missing metrics_s3_uri, NOTIFICATION_SNS_TOPIC_ARN, or ATHENA_RESULTS_BUCKET environment variable.")

        raise ValueError("Missing required input or configuration.")



    # Load metrics JSON from S3

    metrics_bucket, metrics_key = parse_s3_uri(metrics_s3_uri)

    metrics_json_body = s3_client.get_object(metrics_bucket, metrics_key)

    metrics = json.loads(metrics_json_body)

    logger.info(f"Loaded metrics: {metrics}")



    # Generate summary

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



    # Publish to SNS

    sns_response = sns_client.publish_message(

        topic_arn=NOTIFICATION_SNS_TOPIC_ARN,

        message=summary_message,

        subject=f"Incident Replay Report - {scenario}"

    )

    sns_message_id = sns_response.get("MessageId")

    logger.info(f"Report published to SNS with MessageId: {sns_message_id}")



    artifact_prefix = None

    if not summary_only:

        # Upload artifacts (metrics JSON and potentially a CSV version) to S3 /artifacts/ path

        output_timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")

        artifact_base_key = f"artifacts/{scenario.replace(' ', '_')}_{output_timestamp}"



        # Save metrics JSON as artifact

        artifact_json_key = f"{artifact_base_key}.json"

        s3_client.put_object(

            bucket_name=ATHENA_RESULTS_BUCKET,

            key=artifact_json_key,

            body=json.dumps(metrics, indent=2)

        )

        logger.info(f"Metrics JSON artifact saved to s3://{ATHENA_RESULTS_BUCKET}/{artifact_json_key}")



        # Generate and save CSV artifact

        if metrics:

            csv_buffer = StringIO()

            # Assuming metrics is a flat dictionary for CSV conversion

            writer = csv.DictWriter(csv_buffer, fieldnames=metrics.keys())

            writer.writeheader()

            writer.writerow(metrics)

            artifact_csv_key = f"{artifact_base_key}.csv"

            s3_client.put_object(

                bucket_name=ATHENA_RESULTS_BUCKET,

                key=artifact_csv_key,

                body=csv_buffer.getvalue()

            )

            logger.info(f"Metrics CSV artifact saved to s3://{ATHENA_RESULTS_BUCKET}/{artifact_csv_key}")

        

        artifact_prefix = f"s3://{ATHENA_RESULTS_BUCKET}/{artifact_base_key}"



    return {

        "statusCode": 200,

        "body": json.dumps({

            "notified": True,

            "sns_message_id": sns_message_id,

            "artifact_prefix": artifact_prefix

        })

    }
