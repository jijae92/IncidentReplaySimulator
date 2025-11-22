# src/detector_adapter_stub/handler.py

import json

import os

import pandas as pd

from io import StringIO

from datetime import datetime

from urllib.parse import urlparse



from aws_lambda_powertools import Logger

from aws_lambda_powertools.utilities.typing import LambdaContext



from s3 import S3Client
try:
    from schemas import DetectionResult  # noqa
except Exception:  # pragma: no cover
    from typing import List

    from pydantic import BaseModel

    class _Detection(BaseModel):
        rule_id: str
        message: str
        severity: str

    class DetectionResult(BaseModel):
        detections: List[_Detection] = []
        total_matches: int = 0
        unique_actors: int = 0
        unique_src_ips: int = 0
from config import get_config

logger = Logger(service="detector_adapter_stub")


def _normalize_for_merge(df: pd.DataFrame, tag: str) -> pd.DataFrame:
    """
    Prepare a single-column DataFrame with normalized event IDs for merging.
    tag should be 'res' or 'base'.

    Priority:
    1. Use an existing eventID column (case-insensitive match).
    2. If missing, map `_col0` to the event ID.
    3. If still missing, synthesize deterministic IDs like 'res-0', 'base-0', ...
    """
    if df is None:
        raise ValueError("DataFrame for normalization cannot be None.")

    normalized_column = f"eventID_{tag}"
    cols_lc = {str(col).lower(): col for col in df.columns}

    if "eventid" in cols_lc:
        source_col = cols_lc["eventid"]
        out = df[[source_col]].rename(columns={source_col: normalized_column})
    elif "_col0" in df.columns:
        out = df[["_col0"]].rename(columns={"_col0": normalized_column})
    else:
        synthesized = [f"{tag}-{idx}" for idx in range(len(df))]
        out = pd.DataFrame({normalized_column: synthesized})

    out = out.copy()
    if out[normalized_column].isna().any():
        filler = (f"{tag}-auto-{idx}" for idx in range(len(out)))
        out[normalized_column] = [
            value if pd.notna(value) else next(filler) for value in out[normalized_column]
        ]

    return out.drop_duplicates(ignore_index=True)


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Parses an S3 URI into bucket name and key."""
    parsed_uri = urlparse(s3_uri)
    if parsed_uri.scheme != "s3":
        raise ValueError(f"Invalid S3 URI scheme: {s3_uri}")
    bucket_name = parsed_uri.netloc
    key = parsed_uri.path.lstrip('/')
    return bucket_name, key

def calculate_metrics(results_df: pd.DataFrame, baseline_df: pd.DataFrame) -> dict:
    """Calculates detection metrics (TP, FP, FN, precision, recall, F1)."""
    res_norm = _normalize_for_merge(results_df, "res")
    base_norm = _normalize_for_merge(baseline_df, "base")

    merged_df = res_norm.merge(
        base_norm,
        left_on="eventID_res",
        right_on="eventID_base",
        how="outer",
        indicator=True,
    )
    merged_df["is_match"] = merged_df["_merge"] == "both"

    tp = int((merged_df["_merge"] == "both").sum())
    fp = int((merged_df["_merge"] == "left_only").sum())
    fn = int((merged_df["_merge"] == "right_only").sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1
    }

def lambda_handler(event: dict, context: LambdaContext) -> dict:
    logger.info(f"Received event: {event}")

    config = get_config()
    s3_client = S3Client(region=config.aws_region)

    results_s3_uri = event.get("results_s3_uri")
    baseline_s3_uri = event.get("baseline_s3_uri")

    if not all([results_s3_uri, baseline_s3_uri, config.athena_results_bucket]):
        logger.error("Missing results_s3_uri, baseline_s3_uri, or ATHENA_RESULTS_BUCKET environment variable.")
        raise ValueError("Missing required input or configuration.")

    # Load results CSV
    results_bucket, results_key = parse_s3_uri(results_s3_uri)
    results_csv_body = s3_client.get_object(results_bucket, results_key)
    results_df = pd.read_csv(StringIO(results_csv_body))
    logger.info(f"Loaded {results_df.shape[0]} rows from results CSV: {results_s3_uri}")

    # Load baseline CSV
    baseline_bucket, baseline_key = parse_s3_uri(baseline_s3_uri)
    baseline_csv_body = s3_client.get_object(baseline_bucket, baseline_key)
    baseline_df = pd.read_csv(StringIO(baseline_csv_body))
    logger.info(f"Loaded {baseline_df.shape[0]} rows from baseline CSV: {baseline_s3_uri}")

    # Calculate metrics
    metrics = calculate_metrics(results_df, baseline_df)
    logger.info(f"Calculated metrics: {metrics}")

    # Save metrics to S3
    output_timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    metrics_s3_key = f"irs/metrics/metrics_{output_timestamp}.json"
    s3_client.put_object(
        bucket_name=config.athena_results_bucket,
        key=metrics_s3_key,
        body=json.dumps(metrics, indent=2)
    )
    report_s3_uri = f"s3://{config.athena_results_bucket}/{metrics_s3_key}"
    logger.info(f"Metrics saved to {report_s3_uri}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "f1": metrics["f1"],
            "tp": metrics["tp"],
            "fp": metrics["fp"],
            "fn": metrics["fn"],
            "report": report_s3_uri
        })
    }
