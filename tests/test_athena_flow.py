import pytest
import boto3
from botocore.stub import Stubber
import time
from io import StringIO, BytesIO
import csv
from unittest.mock import patch

from src.common.athena import AthenaClient

# Mock data
TEST_REGION = "ap-northeast-2"
TEST_WORKGROUP = "test-workgroup"
TEST_DATABASE = "test-database"
TEST_OUTPUT_LOCATION = "s3://test-results-bucket/athena/results/"
TEST_SQL = "SELECT * FROM test_table WHERE col = :value"
TEST_PARAMS = {"value": "test_value"}
TEST_QUERY_ID = "test-query-123"

@pytest.fixture
def athena_stubber():
    with Stubber(boto3.client("athena", region_name=TEST_REGION)) as stubber:
        yield stubber

@pytest.fixture
def s3_stubber():
    with Stubber(boto3.client("s3", region_name=TEST_REGION)) as stubber:
        yield stubber

@pytest.fixture
def athena_client(athena_stubber, s3_stubber):
    client = AthenaClient(region=TEST_REGION)
    client.athena = athena_stubber.client
    client.s3 = s3_stubber.client
    return client

def test_start_query_successfully(athena_client, athena_stubber):
    expected_params = {
        "QueryString": TEST_SQL.replace(":value", "'test_value'"),
        "QueryExecutionContext": {"Database": TEST_DATABASE},
        "ResultConfiguration": {"OutputLocation": TEST_OUTPUT_LOCATION},
        "WorkGroup": TEST_WORKGROUP,
    }
    athena_stubber.add_response(
        "start_query_execution",
        {"QueryExecutionId": TEST_QUERY_ID},
        expected_params,
    )

    query_id = athena_client.start_query(
        sql=TEST_SQL,
        params=TEST_PARAMS,
        workgroup=TEST_WORKGROUP,
        output_s3=TEST_OUTPUT_LOCATION,
        database=TEST_DATABASE,
    )
    assert query_id == TEST_QUERY_ID
    athena_stubber.assert_no_pending_responses()

def test_wait_query_succeeded(athena_client, athena_stubber):
    # Simulate QUEUED -> RUNNING -> SUCCEEDED
    athena_stubber.add_response(
        "get_query_execution",
        {"QueryExecution": {"Status": {"State": "QUEUED"}}},
        {"QueryExecutionId": TEST_QUERY_ID},
    )
    athena_stubber.add_response(
        "get_query_execution",
        {"QueryExecution": {"Status": {"State": "RUNNING"}}},
        {"QueryExecutionId": TEST_QUERY_ID},
    )
    athena_stubber.add_response(
        "get_query_execution",
        {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}},
        {"QueryExecutionId": TEST_QUERY_ID},
    )

    query_execution = athena_client.wait_query(TEST_QUERY_ID, poll_interval_seconds=0.01)
    assert query_execution["Status"]["State"] == "SUCCEEDED"
    athena_stubber.assert_no_pending_responses()

def test_wait_query_failed(athena_client, athena_stubber):
    athena_stubber.add_response(
        "get_query_execution",
        {"QueryExecution": {"Status": {"State": "FAILED", "StateChangeReason": "User error"}}},
        {"QueryExecutionId": TEST_QUERY_ID},
    )

    query_execution = athena_client.wait_query(TEST_QUERY_ID, poll_interval_seconds=0.01)
    assert query_execution["Status"]["State"] == "FAILED"
    assert query_execution["Status"]["StateChangeReason"] == "User error"
    athena_stubber.assert_no_pending_responses()

def test_wait_query_timeout(athena_client):
    with patch.object(athena_client.athena, 'get_query_execution', return_value={'QueryExecution': {'Status': {'State': 'RUNNING'}}}) as mock_get:
        with patch.object(athena_client.athena, 'stop_query_execution') as mock_stop:
            with pytest.raises(TimeoutError, match=f"Athena query {TEST_QUERY_ID} timed out"):
                athena_client.wait_query(TEST_QUERY_ID, poll_interval_seconds=0.01, timeout_seconds=0.05)

            # Assert that stop_query_execution was called because of the timeout
            mock_stop.assert_called_once_with(QueryExecutionId=TEST_QUERY_ID)

def test_fetch_results_successfully(athena_client, s3_stubber):
    mock_csv_content = b"col1,col2\nval1,val2\nval3,val4"
    expected_results = [
        {"col1": "val1", "col2": "val2"},
        {"col1": "val3", "col2": "val4"},
    ]

    s3_stubber.add_response(
        "get_object",
        {"Body": BytesIO(mock_csv_content)},
        {"Bucket": "test-results-bucket", "Key": f"athena/results/{TEST_QUERY_ID}.csv"},
    )

    results = athena_client.fetch_results(TEST_QUERY_ID, TEST_OUTPUT_LOCATION)
    assert results == expected_results
    s3_stubber.assert_no_pending_responses()

def test_fetch_results_no_such_key_then_txt(athena_client, s3_stubber):
    mock_txt_content = b"colA,colB\nvalA,valB"
    expected_results = [
        {"colA": "valA", "colB": "valB"},
    ]

    # First try .csv, expect NoSuchKey
    s3_stubber.add_client_error(
        "get_object",
        service_error_code="NoSuchKey",
        service_message="The specified key does not exist.",
        expected_params={
            "Bucket": "test-results-bucket",
            "Key": f"athena/results/{TEST_QUERY_ID}.csv",
        },
    )

    # Then try .txt, expect success
    s3_stubber.add_response(
        "get_object",
        {"Body": BytesIO(mock_txt_content)},
        {"Bucket": "test-results-bucket", "Key": f"athena/results/{TEST_QUERY_ID}.txt"},
    )

    results = athena_client.fetch_results(TEST_QUERY_ID, TEST_OUTPUT_LOCATION)
    assert results == expected_results
    s3_stubber.assert_no_pending_responses()

def test_fetch_results_no_such_key_both_formats(athena_client, s3_stubber):
    # Try .csv, expect NoSuchKey
    s3_stubber.add_client_error(
        "get_object",
        service_error_code="NoSuchKey",
        service_message="The specified key does not exist.",
        expected_params={
            "Bucket": "test-results-bucket",
            "Key": f"athena/results/{TEST_QUERY_ID}.csv",
        },
    )

    # Try .txt, expect NoSuchKey
    s3_stubber.add_client_error(
        "get_object",
        service_error_code="NoSuchKey",
        service_message="The specified key does not exist.",
        expected_params={
            "Bucket": "test-results-bucket",
            "Key": f"athena/results/{TEST_QUERY_ID}.txt",
        },
    )

    with pytest.raises(FileNotFoundError, match="Athena query results not found"):
        athena_client.fetch_results(TEST_QUERY_ID, TEST_OUTPUT_LOCATION)
    s3_stubber.assert_no_pending_responses()