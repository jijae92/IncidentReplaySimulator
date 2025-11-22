# src/common/s3.py

import boto3

import json

import csv

from io import StringIO, BytesIO

from typing import List, Dict, Any



class S3Client:

    def __init__(self, region: str = "ap-northeast-2"):

        self.s3 = boto3.client("s3", region_name=region)



    def put_object(self, bucket_name: str, key: str, body: Any, content_type: str = "application/octet-stream") -> Dict[str, Any]:

        """Uploads a string or bytes to an S3 object."""

        response = self.s3.put_object(

            Bucket=bucket_name,

            Key=key,

            Body=body,

            ContentType=content_type

        )

        return response



    def put_json(self, bucket_name: str, key: str, data: Dict[str, Any]) -> Dict[str, Any]:

        """Uploads a JSON object to S3."""

        return self.put_object(bucket_name, key, json.dumps(data), content_type="application/json")



    def put_csv(self, bucket_name: str, key: str, data: List[Dict[str, Any]], fieldnames: List[str]) -> Dict[str, Any]:

        """Uploads a list of dictionaries as CSV to S3."""

        csv_buffer = StringIO()

        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)

        writer.writeheader()

        writer.writerows(data)

        return self.put_object(bucket_name, key, csv_buffer.getvalue(), content_type="text/csv")



    def get_object(self, bucket_name: str, key: str) -> str:

        """Downloads an S3 object as a string (UTF-8 decoded)."""

        response = self.s3.get_object(

            Bucket=bucket_name,

            Key=key

        )

        return response["Body"].read().decode("utf-8")



    def get_object_bytes(self, bucket_name: str, key: str) -> bytes:

        """Downloads an S3 object as bytes."""

        response = self.s3.get_object(

            Bucket=bucket_name,

            Key=key

        )

        return response["Body"].read()



    def list_objects(self, bucket_name: str, prefix: str = "") -> List[str]:

        """Lists objects in an S3 bucket with a given prefix."""

        keys = []

        paginator = self.s3.get_paginator("list_objects_v2")

        pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

        for page in pages:

            if "Contents" in page:

                for obj in page["Contents"]:

                    keys.append(obj["Key"])

        return keys



# TODO: Add error handling and logging
