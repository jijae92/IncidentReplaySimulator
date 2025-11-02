# src/common/sns.py

import boto3
import json
from typing import Dict, Any

class SnsClient:
    def __init__(self, region: str = "ap-northeast-2"):
        self.sns = boto3.client("sns", region_name=region)

    def publish_message(self, topic_arn: str, message: str, subject: str = "") -> Dict[str, Any]:
        """Publishes a string message to an SNS topic."""
        response = self.sns.publish(
            TopicArn=topic_arn,
            Message=message,
            Subject=subject
        )
        return response

    def publish_json(self, topic_arn: str, message: Dict[str, Any], subject: str = "") -> Dict[str, Any]:
        """Publishes a JSON message to an SNS topic."""
        return self.publish_message(topic_arn, json.dumps(message), subject)

# TODO: Add error handling and logging
