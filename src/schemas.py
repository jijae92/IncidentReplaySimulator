# src/common/schemas.py

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Detection(BaseModel):
    rule_id: str = Field(..., description="Detector rule identifier")
    message: str = Field(..., description="Human-readable finding message")
    severity: str = Field(..., description="INFO|LOW|MEDIUM|HIGH|CRITICAL")
    actor: Optional[str] = None
    src_ip: Optional[str] = None
    event_time: Optional[str] = None  # ISO8601
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DetectionResult(BaseModel):
    detections: List[Detection] = Field(default_factory=list)
    total_matches: int = 0
    unique_actors: int = 0
    unique_src_ips: int = 0

    @classmethod
    def from_detections(cls, dets: List[Detection]) -> "DetectionResult":
        actors = {d.actor for d in dets if d.actor}
        srcs = {d.src_ip for d in dets if d.src_ip}
        return cls(
            detections=dets,
            total_matches=len(dets),
            unique_actors=len(actors),
            unique_src_ips=len(srcs),
        )


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
