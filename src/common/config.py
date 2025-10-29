import os
from typing import Optional

class IRSConfig:
    def __init__(
        self,
        athena_workgroup: str = os.getenv('IRS_ATHENA_WORKGROUP', os.getenv('ATHENA_WORKGROUP', 'primary')),
        results_bucket: Optional[str] = os.getenv('IRS_RESULTS_BUCKET'),
        replay_bucket: Optional[str] = os.getenv('IRS_REPLAY_BUCKET'),
        glue_database: Optional[str] = os.getenv('IRS_GLUE_DATABASE'),
        sns_topic_arn: Optional[str] = os.getenv('IRS_SNS_TOPIC_ARN', os.getenv('SNS_TOPIC_ARN')),
        log_account_id: str = os.getenv('LOG_ACCOUNT_ID', ''),
        query_timeout_seconds: int = int(os.getenv('QUERY_TIMEOUT_SECONDS', 60)),
        max_retries: int = int(os.getenv('MAX_RETRIES', 5)),
    ):
        self.athena_workgroup = athena_workgroup
        self.results_bucket = results_bucket
        self.replay_bucket = replay_bucket
        self.glue_database = glue_database
        self.sns_topic_arn = sns_topic_arn
        self.log_account_id = log_account_id
        self.query_timeout_seconds = query_timeout_seconds
        self.max_retries = max_retries

def load_config() -> IRSConfig:
    return IRSConfig()