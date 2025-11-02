import pytest
import json
import os
import csv
import importlib
from io import StringIO, BytesIO
from unittest.mock import patch

import boto3
from moto import mock_aws

# Import modules that need reloading
from src.reporter import handler as reporter_handler
from src.common import config as common_config
from src.common.sns import SnsClient
from src.common.s3 import S3Client

# Mock data
TEST_REGION = "ap-northeast-2"
TEST_ATHENA_RESULTS_BUCKET = "test-athena-results-bucket"
TEST_SNS_TOPIC_NAME = "test-notification-topic"
TEST_SNS_TOPIC_ARN = f"arn:aws:sns:{TEST_REGION}:123456789012:{TEST_SNS_TOPIC_NAME}"
TEST_QUERY_EXECUTION_ID = "test-query-123"

@pytest.fixture(scope="function")
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = TEST_REGION

@pytest.fixture(scope="function")
def aws_mocks(aws_credentials):
    with mock_aws():
        yield

@pytest.fixture(scope="function")
def s3_client_mock(aws_mocks):
    client = boto3.client("s3", region_name=TEST_REGION)
    client.create_bucket(Bucket=TEST_ATHENA_RESULTS_BUCKET, CreateBucketConfiguration={'LocationConstraint': TEST_REGION})
    return client

@pytest.fixture(scope="function")
def sns_client_mock(aws_mocks):
    client = boto3.client("sns", region_name=TEST_REGION)
    client.create_topic(Name=TEST_SNS_TOPIC_NAME)
    return client

@pytest.fixture
def reload_modules_and_patch(monkeypatch, s3_client_mock, sns_client_mock):
    monkeypatch.setenv("NOTIFICATION_SNS_TOPIC_ARN", TEST_SNS_TOPIC_ARN)
    monkeypatch.setenv("ATHENA_RESULTS_BUCKET", TEST_ATHENA_RESULTS_BUCKET)
    monkeypatch.setenv("AWS_REGION", TEST_REGION)
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "reporter")

    importlib.reload(common_config)
    importlib.reload(reporter_handler)

    def mock_boto3_client(service_name, *args, **kwargs):
        if service_name == 'sns':
            return sns_client_mock
        if service_name == 's3':
            return s3_client_mock
        # Fallback to the real boto3.client for other services
        return boto3.client(service_name, *args, **kwargs)

    with patch("boto3.client", side_effect=mock_boto3_client):
        yield

@pytest.fixture
def sample_metrics_data():
    return {
        "scenario": "iam_createuser",
        "precision": 0.95,
        "recall": 0.85,
        "f1": 0.90,
        "tp": 95,
        "fp": 5,
        "fn": 15,
        "query_execution_id": TEST_QUERY_EXECUTION_ID,
        "result_s3_json": f"s3://{TEST_ATHENA_RESULTS_BUCKET}/irs/queries/{TEST_QUERY_EXECUTION_ID}.json",
        "result_s3_csv": f"s3://{TEST_ATHENA_RESULTS_BUCKET}/irs/queries/{TEST_QUERY_EXECUTION_ID}.csv"
    }

def test_reporter_publishes_sns_and_saves_artifacts(s3_client_mock, reload_modules_and_patch, sample_metrics_data):
    metrics_s3_key = f"irs/metrics/{TEST_QUERY_EXECUTION_ID}.json"
    s3_client_mock.put_object(
        Bucket=TEST_ATHENA_RESULTS_BUCKET,
        Key=metrics_s3_key,
        Body=json.dumps(sample_metrics_data)
    )
    metrics_s3_uri = f"s3://{TEST_ATHENA_RESULTS_BUCKET}/{metrics_s3_key}"

    event = {"metrics_s3": metrics_s3_uri, "summary_only": False}

    response = reporter_handler.lambda_handler(event, None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["notified"] is True
    assert "sns_message_id" in body
    assert body["artifact_prefix"] is not None

    artifact_objects = s3_client_mock.list_objects_v2(Bucket=TEST_ATHENA_RESULTS_BUCKET, Prefix="artifacts/")["Contents"]
    assert len(artifact_objects) == 2

def test_reporter_handles_summary_only(s3_client_mock, reload_modules_and_patch, sample_metrics_data):
    metrics_s3_key = f"irs/metrics/{TEST_QUERY_EXECUTION_ID}.json"
    s3_client_mock.put_object(
        Bucket=TEST_ATHENA_RESULTS_BUCKET,
        Key=metrics_s3_key,
        Body=json.dumps(sample_metrics_data)
    )
    metrics_s3_uri = f"s3://{TEST_ATHENA_RESULTS_BUCKET}/{metrics_s3_key}"

    event = {"metrics_s3": metrics_s3_uri, "summary_only": True}

    response = reporter_handler.lambda_handler(event, None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["artifact_prefix"] is None

    objects = s3_client_mock.list_objects_v2(Bucket=TEST_ATHENA_RESULTS_BUCKET, Prefix="artifacts/")
    assert "Contents" not in objects

def test_reporter_handles_missing_config(monkeypatch):
    monkeypatch.setenv("NOTIFICATION_SNS_TOPIC_ARN", "")
    monkeypatch.setenv("ATHENA_RESULTS_BUCKET", "")
    importlib.reload(common_config)
    importlib.reload(reporter_handler)

    event = {"metrics_s3": "s3://some-bucket/some-key"}
    with pytest.raises(ValueError, match="Missing required input or configuration."):
        reporter_handler.lambda_handler(event, None)
