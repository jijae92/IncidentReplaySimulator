import pytest
import json
import gzip
import os
import re
import importlib
from datetime import datetime, timedelta
from unittest.mock import patch

import boto3
from moto import mock_aws

# Import the modules that need to be reloaded
from src.ingest_replay_log import handler as ingest_handler
from src.common import config as common_config
from src.common.s3 import S3Client

# Mock data
TEST_REGION = "ap-northeast-2"
TEST_ACCOUNT_ID = "123456789012"
TEST_REPLAY_BUCKET = "test-replay-bucket"

@pytest.fixture(scope="function")
def aws_credentials():
    "Mocked AWS Credentials for moto."
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = TEST_REGION

@pytest.fixture(scope="function")
def s3_client_mock(aws_credentials):
    with mock_aws():
        client = boto3.client("s3", region_name=TEST_REGION)
        client.create_bucket(Bucket=TEST_REPLAY_BUCKET, CreateBucketConfiguration={'LocationConstraint': TEST_REGION})
        yield client

@pytest.fixture
def reload_modules(monkeypatch):
    """Sets env vars and reloads modules to ensure they are picked up."""
    monkeypatch.setenv("BUCKET_REPLAY", TEST_REPLAY_BUCKET)
    monkeypatch.setenv("AWS_REGION", TEST_REGION)
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "ingest_replay_log")
    
    importlib.reload(common_config)
    importlib.reload(ingest_handler)
    yield

def test_ingest_replay_log_creates_s3_object(s3_client_mock, reload_modules):
    event = {
        "count": 1,
        "accountId": TEST_ACCOUNT_ID,
        "region": TEST_REGION,
        "startTime": (datetime.utcnow() - timedelta(minutes=5)).isoformat() + "Z"
    }
    
    # Use the reloaded handler
    response = ingest_handler.lambda_handler(event, None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "objects" in body
    assert len(body["objects"]) == 1

    # Verify object exists in S3
    objects = s3_client_mock.list_objects_v2(Bucket=TEST_REPLAY_BUCKET)["Contents"]
    assert len(objects) == 1
    assert objects[0]["Key"].startswith(f"AWSLogs/{TEST_ACCOUNT_ID}/CloudTrail/{TEST_REGION}/")

def test_ingest_replay_log_uses_correct_s3_key_format(s3_client_mock, reload_modules):
    test_start_time = datetime(2023, 1, 1, 10, 0, 0)
    event = {
        "count": 1,
        "accountId": TEST_ACCOUNT_ID,
        "region": TEST_REGION,
        "startTime": test_start_time.isoformat() + "Z"
    }

    response = ingest_handler.lambda_handler(event, None)
    body = json.loads(response["body"])
    s3_path = body["objects"][0]
    
    s3_key = s3_path.replace(f"s3://{TEST_REPLAY_BUCKET}/", "")

    expected_key_pattern = re.compile(
        rf"AWSLogs/{TEST_ACCOUNT_ID}/CloudTrail/{TEST_REGION}/"
        rf"{test_start_time.strftime('%Y/%m/%d')}/"
        rf"{TEST_ACCOUNT_ID}_CloudTrail_{TEST_REGION}_{test_start_time.strftime('%Y%m%dT%H%MZ')}_"
        r"[0-9a-fA-F-]{36}\.json\.gz"
    )
    assert expected_key_pattern.match(s3_key)

    obj = s3_client_mock.get_object(Bucket=TEST_REPLAY_BUCKET, Key=s3_key)
    decompressed_data = gzip.decompress(obj["Body"].read()).decode("utf-8")
    cloudtrail_records = json.loads(decompressed_data)
    assert "Records" in cloudtrail_records
    assert len(cloudtrail_records["Records"]) == 3

def test_ingest_replay_log_handles_missing_bucket_env_var(monkeypatch):
    monkeypatch.setenv("BUCKET_REPLAY", "")
    importlib.reload(common_config)
    importlib.reload(ingest_handler)

    event = {"count": 1}
    with pytest.raises(ValueError, match="BUCKET_REPLAY environment variable is not set."):
        ingest_handler.lambda_handler(event, None)
