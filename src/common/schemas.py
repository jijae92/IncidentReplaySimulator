# src/common/schemas.py

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class CloudTrailEvent(BaseModel):
    eventVersion: str
    userIdentity: Dict[str, Any]
    eventTime: str
    eventSource: str
    eventName: str
    awsRegion: str
    sourceIPAddress: str
    requestParameters: Optional[Dict[str, Any]]
    responseElements: Optional[Dict[str, Any]]
    eventID: str
    eventType: str
    recipientAccountId: str
    # Add other relevant CloudTrail fields as needed

class AthenaQueryExecutionResult(BaseModel):
    queryExecutionId: str
    status: str
    outputLocation: str
    # Add other relevant Athena query execution fields

class CreateUserSequenceResult(BaseModel):
    actor_arn: str
    target_user: str
    first_event_time: str
    last_event_time: str
    src_ip: str
    user_agent: str
    sequence_score: int

class DetectionMetrics(BaseModel):
    tp: int = Field(..., description="True Positives")
    fp: int = Field(..., description="False Positives")
    fn: int = Field(..., description="False Negatives")
    precision: float = Field(..., description="Precision score")
    recall: float = Field(..., description="Recall score")
    f1: float = Field(..., description="F1 score")

class ReportMetrics(BaseModel):
    scenario: str
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    query_execution_id: str
    result_s3_json: str
    result_s3_csv: str

class ReportOutput(BaseModel):
    notified: bool
    sns_message_id: Optional[str]
    artifact_prefix: Optional[str]

# TODO: Add more specific schemas for requestParameters and responseElements if needed
