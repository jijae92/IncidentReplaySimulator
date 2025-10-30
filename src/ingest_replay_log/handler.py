# src/ingest_replay_log/handler.py

import json

import os

import uuid

import gzip

from datetime import datetime, timedelta

from typing import List, Dict, Any



from aws_lambda_powertools import Logger

from aws_lambda_powertools.utilities.typing import LambdaContext



from src.common.s3 import S3Client



from src.common.config import BUCKET_REPLAY, AWS_REGION



logger = Logger(service="ingest_replay_log")

s3_client = S3Client(region=AWS_REGION)



def generate_cloudtrail_event(event_name: str, account_id: str, region: str, start_time: datetime, user_name: str, access_key_id: str = None) -> Dict[str, Any]:

    """Generates a sample CloudTrail event for a given event name."""

    event_id = str(uuid.uuid4())

    event_time = start_time.isoformat(timespec='milliseconds') + "Z"



    base_event = {

        "eventVersion": "1.08",

        "userIdentity": {

            "type": "IAMUser",

            "principalId": f"AIDACKCEVSQ6C2EXAMPLE-{user_name}",

            "arn": f"arn:aws:iam::{account_id}:user/{user_name}",

            "accountId": account_id,

            "accessKeyId": access_key_id if access_key_id else f"AKIAIOSFODNN7EXAMPLE-{user_name}",

            "userName": user_name

        },

        "eventTime": event_time,

        "eventSource": "iam.amazonaws.com",

        "eventName": event_name,

        "awsRegion": region,

        "sourceIPAddress": "192.0.2.1",

        "userAgent": "console.amazonaws.com",

        "eventID": event_id,

        "eventType": "AwsApiCall",

        "recipientAccountId": account_id

    }



    if event_name == "CreateUser":

        base_event["requestParameters"] = {"userName": user_name}

        base_event["responseElements"] = {"user": {"createDate": event_time, "userName": user_name, "userId": f"AIDACKCEVSQ6C2EXAMPLE-{user_name}"}}

    elif event_name == "AttachUserPolicy" or event_name == "PutUserPolicy":

        base_event["requestParameters"] = {"userName": user_name, "policyArn": f"arn:aws:iam::aws:policy/AdministratorAccess"}

        base_event["responseElements"] = {"ResponseMetadata": {"RequestId": str(uuid.uuid4())}}

    elif event_name == "CreateAccessKey":

        base_event["requestParameters"] = {"userName": user_name}

        base_event["responseElements"] = {"accessKey": {"accessKeyId": access_key_id, "status": "Active"}}



    return base_event



def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:

    logger.info(f"Received event: {event}")



    scenario = event.get("scenario", "iam_createuser")

    count = event.get("count", 1)

    start_time_str = event.get("startTime", datetime.utcnow().isoformat() + "Z")

    account_id = event.get("accountId", "123456789012") # TODO: Use actual account ID

    region = event.get("region", AWS_REGION)



    if not BUCKET_REPLAY:

        logger.error("BUCKET_REPLAY environment variable is not set.")

        raise ValueError("BUCKET_REPLAY environment variable is not set.")



    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))

    generated_objects = []



    for i in range(count):

        user_name = f"malicious-user-{uuid.uuid4().hex[:8]}"

        access_key_id = f"AKIA{uuid.uuid4().hex[:16].upper()}"

        current_event_time = start_time + timedelta(minutes=i)



        # Generate sequence of events for the scenario

        events_for_sequence = [

            generate_cloudtrail_event("CreateUser", account_id, region, current_event_time, user_name),

            generate_cloudtrail_event("AttachUserPolicy", account_id, region, current_event_time + timedelta(seconds=10), user_name),

            generate_cloudtrail_event("CreateAccessKey", account_id, region, current_event_time + timedelta(seconds=20), user_name, access_key_id)

        ]



        # Each sequence of events forms a single CloudTrail log file

        cloudtrail_records = {"Records": events_for_sequence}

        json_data = json.dumps(cloudtrail_records)



        # Gzip compression

        compressed_data = gzip.compress(json_data.encode('utf-8'))



        # S3 Key format: AWSLogs/{accountId}/CloudTrail/{region}/{yyyy}/{mm}/{dd}/{accountId}_CloudTrail_{region}_{yyyy}{mm}{dd}T{HH}{MM}Z_{GUID}.json.gz

        s3_key_timestamp = current_event_time.strftime("%Y%m%dT%H%MZ")

        s3_key_date_path = current_event_time.strftime("%Y/%m/%d")

        guid = str(uuid.uuid4())



        s3_key = (

            f"AWSLogs/{account_id}/CloudTrail/{region}/"

            f"{s3_key_date_path}/"

            f"{account_id}_CloudTrail_{region}_{s3_key_timestamp}_{guid}.json.gz"

        )



        try:

            s3_client.put_object(

                bucket_name=BUCKET_REPLAY,

                key=s3_key,

                body=compressed_data

            )

            generated_objects.append(f"s3://{BUCKET_REPLAY}/{s3_key}")

            logger.info(f"Successfully ingested replay log to s3://{BUCKET_REPLAY}/{s3_key}")

        except Exception as e:

            logger.error(f"Failed to ingest replay log to {s3_key}: {e}")

            raise



    return {

        "statusCode": 200,

        "body": json.dumps({"message": "Replay logs ingested successfully", "objects": generated_objects, "count": len(generated_objects)})

    }
