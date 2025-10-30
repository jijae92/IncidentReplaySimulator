# src/common/athena.py

import boto3

import time

from typing import Dict, Any, List, Optional



class AthenaClient:

    def __init__(self, region: str = "ap-northeast-2"):

        self.athena = boto3.client("athena", region_name=region)

        self.s3 = boto3.client("s3", region_name=region)



    def start_query(self, sql: str, params: Dict[str, str], workgroup: str, output_s3: str, database: str) -> str:

        """Starts an Athena query execution with parameter binding."""

        query_string_with_params = sql

        for key, value in params.items():

            query_string_with_params = query_string_with_params.replace(f":{key}", f"'{value}'")



        response = self.athena.start_query_execution(

            QueryString=query_string_with_params,

            QueryExecutionContext={

                "Database": database

            },

            ResultConfiguration={

                "OutputLocation": output_s3

            },

            WorkGroup=workgroup

        )

        return response["QueryExecutionId"]



    def wait_query(self, query_execution_id: str, poll_interval_seconds: int = 2, timeout_seconds: int = 600) -> Dict[str, Any]:

        """Polls the status of an Athena query until it completes or times out."""

        start_time = time.time()

        while True:

            response = self.athena.get_query_execution(QueryExecutionId=query_execution_id)

            query_execution = response["QueryExecution"]

            status = query_execution["Status"]["State"]



            if status in ["SUCCEEDED", "FAILED", "CANCELLED"]:

                return query_execution



            if time.time() - start_time > timeout_seconds:

                self.athena.stop_query_execution(QueryExecutionId=query_execution_id)

                raise TimeoutError(f"Athena query {query_execution_id} timed out after {timeout_seconds} seconds.")



            time.sleep(poll_interval_seconds)



    def fetch_results(self, query_execution_id: str, output_location: str, page_size: int = 1000) -> List[Dict[str, Any]]:

        """Fetches results of a completed Athena query from S3 and returns them as a list of dictionaries."""

        # Athena results are typically stored as CSV/JSON in S3 at the output_location

        # The actual result file will be at output_location + query_execution_id + ".csv" (or .txt, .json)

        # We need to parse the S3 path from the output_location

        

        # Example output_location: s3://athena-results-bucket/athena/results/query_execution_id.csv

        # We need to extract bucket and key prefix

        s3_path_parts = output_location.replace("s3://", "").split("/", 1)

        bucket_name = s3_path_parts[0]

        key_prefix = s3_path_parts[1] if len(s3_path_parts) > 1 else ""



        # The actual result file name is usually query_execution_id.csv or .txt

        # We need to list objects in the prefix to find the exact file

        # TODO: Make this more robust to handle different output formats (CSV, JSON) and potential multiple files

        

        # For now, assume CSV output and try to find the file

        result_key = f"{key_prefix}{query_execution_id}.csv"

        try:

            response = self.s3.get_object(Bucket=bucket_name, Key=result_key)

            csv_data = response["Body"].read().decode('utf-8')

            

            # Parse CSV data

            import csv

            from io import StringIO

            

            reader = csv.reader(StringIO(csv_data))

            headers = next(reader) # First row is headers

            

            results = []

            for row in reader:

                results.append(dict(zip(headers, row)))

            return results

        except self.s3.exceptions.NoSuchKey:

            # If .csv not found, try .txt (default for some Athena outputs)

            result_key = f"{key_prefix}{query_execution_id}.txt"

            try:

                response = self.s3.get_object(Bucket=bucket_name, Key=result_key)

                csv_data = response["Body"].read().decode('utf-8')

                

                import csv

                from io import StringIO

                

                reader = csv.reader(StringIO(csv_data))

                headers = next(reader) # First row is headers

                

                results = []

                for row in reader:

                    results.append(dict(zip(headers, row)))

                return results

            except self.s3.exceptions.NoSuchKey:

                raise FileNotFoundError(f"Athena query results not found at {output_location}{query_execution_id}.csv or .txt")

        except Exception as e:

            raise Exception(f"Error fetching or parsing Athena results: {e}")



# TODO: Add error handling and logging
