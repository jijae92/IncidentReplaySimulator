# src/replay_orchestrator/handler.py

import json

import os

from datetime import datetime

from collections import Counter



from aws_lambda_powertools import Logger

from aws_lambda_powertools.utilities.typing import LambdaContext



from src.common.athena import AthenaClient



from src.common.s3 import S3Client



from src.common.config import (



    ATHENA_WORK_GROUP_NAME,



    ATHENA_OUTPUT_LOCATION,



    GLUE_DATABASE_NAME,



    ATHENA_RESULTS_BUCKET,



    AWS_REGION,



    BUCKET_REPLAY # Assuming BUCKET_REPLAY is where SQL files are stored



)



logger = Logger(service="replay_orchestrator")

athena_client = AthenaClient(region=AWS_REGION)

s3_client = S3Client(region=AWS_REGION)



def lambda_handler(event: dict, context: LambdaContext) -> dict:

    logger.info(f"Received event: {event}")



    from_time_str = event.get("from")

    to_time_str = event.get("to")



    if not all([from_time_str, to_time_str, ATHENA_WORK_GROUP_NAME, ATHENA_OUTPUT_LOCATION, GLUE_DATABASE_NAME, BUCKET_REPLAY]):

        logger.error("Missing one or more required environment variables or event parameters.")

        raise ValueError("Missing required configuration or event parameters.")



    # Load SQL query from S3

    query_file_key = "sql/queries/createuser_sequence.sql"

    try:

        sql_query = s3_client.get_object(

            bucket_name=BUCKET_REPLAY, # Assuming SQL files are in the replay bucket

            key=query_file_key

        )

    except Exception as e:

        logger.error(f"Failed to retrieve Athena query from S3: {e}")

        raise



    # Parameter binding

    query_params = {

        "from_ts": from_time_str,

        "to_ts": to_time_str

    }



    logger.info(f"Starting Athena query with params: {query_params}")

    query_execution_id = athena_client.start_query(

        sql=sql_query,

        params=query_params,

        workgroup=ATHENA_WORK_GROUP_NAME,

        output_s3=ATHENA_OUTPUT_LOCATION,

        database=GLUE_DATABASE_NAME

    )

    logger.info(f"Athena query started with ID: {query_execution_id}")



    try:

        query_execution = athena_client.wait_query(query_execution_id)

        status = query_execution["Status"]["State"]

        logger.info(f"Athena query {query_execution_id} finished with status: {status}")



        if status == "SUCCEEDED":

            # Fetch and process results

            results = athena_client.fetch_results(query_execution_id, ATHENA_OUTPUT_LOCATION)

            logger.info(f"Fetched {len(results)} rows from Athena query.")



            # Save results to S3 (CSV/JSON)

            output_timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")

            output_key_prefix = f"irs/queries/{query_execution_id}"



            # Save as JSON

            json_output_key = f"{output_key_prefix}.json"

            s3_client.put_object(

                bucket_name=ATHENA_RESULTS_BUCKET,

                key=json_output_key,

                body=json.dumps(results, indent=2)

            )

            logger.info(f"Results saved to s3://{ATHENA_RESULTS_BUCKET}/{json_output_key}")



            # Save as CSV (if results are not empty)

            if results:

                import csv

                from io import StringIO

                csv_buffer = StringIO()

                fieldnames = results[0].keys()

                writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)

                writer.writeheader()

                writer.writerows(results)

                csv_output_key = f"{output_key_prefix}.csv"

                s3_client.put_object(

                    bucket_name=ATHENA_RESULTS_BUCKET,

                    key=csv_output_key,

                    body=csv_buffer.getvalue()

                )

                logger.info(f"Results saved to s3://{ATHENA_RESULTS_BUCKET}/{csv_output_key}")



            # Summarize results

            total_count = len(results)

            unique_actors = len(set(r.get("actor_arn") for r in results if r.get("actor_arn")))

            unique_src_ips = len(set(r.get("src_ip") for r in results if r.get("src_ip")))



            summary_stats = {

                "total_matches": total_count,

                "unique_actors": unique_actors,

                "unique_src_ips": unique_src_ips,

                "query_execution_id": query_execution_id,

                "result_s3_json": f"s3://{ATHENA_RESULTS_BUCKET}/{json_output_key}",

                "result_s3_csv": f"s3://{ATHENA_RESULTS_BUCKET}/{csv_output_key}"

            }

            logger.info(f"Query summary: {summary_stats}")



            return {

                "statusCode": 200,

                "body": json.dumps({

                    "message": "Athena query executed and results processed successfully",

                    "summary": summary_stats

                })

            }

        else:

            error_message = query_execution["Status"].get("StateChangeReason", "Unknown error")

            logger.error(f"Athena query failed: {error_message}")

            return {

                "statusCode": 500,

                "body": json.dumps({"message": "Athena query failed", "error": error_message})

            }

    except TimeoutError as e:

        logger.error(f"Athena query timed out: {e}")

        return {

            "statusCode": 500,

            "body": json.dumps({"message": "Athena query timed out", "error": str(e)})

        }

    except Exception as e:

        logger.error(f"An unexpected error occurred during Athena query orchestration: {e}")

        return {

            "statusCode": 500,

            "body": json.dumps({"message": "An unexpected error occurred", "error": str(e)})

        }
