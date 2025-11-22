import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class AppConfig:
    aws_region: str
    bucket_replay: Optional[str]
    athena_results_bucket: Optional[str]
    glue_database_name: Optional[str]
    athena_work_group_name: Optional[str]
    notification_sns_topic_arn: Optional[str]
    athena_output_location: Optional[str]

def get_config() -> AppConfig:
    """Loads configuration from environment variables."""
    results_bucket = os.environ.get("ATHENA_RESULTS_BUCKET")
    return AppConfig(
        aws_region=os.environ.get("AWS_REGION", "ap-northeast-2"),
        bucket_replay=os.environ.get("BUCKET_REPLAY"),
        athena_results_bucket=results_bucket,
        glue_database_name=os.environ.get("GLUE_DATABASE_NAME"),
        athena_work_group_name=os.environ.get("ATHENA_WORK_GROUP_NAME"),
        notification_sns_topic_arn=os.environ.get("NOTIFICATION_SNS_TOPIC_ARN"),
        athena_output_location=f"s3://{results_bucket}/athena/results/" if results_bucket else None
    )
