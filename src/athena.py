from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import boto3


class AthenaClient:
    """Thin wrapper around the Athena SDK with convenience helpers."""

    def __init__(self, region: str = "ap-northeast-2") -> None:
        self.athena = boto3.client("athena", region_name=region)

    def start_query(
        self,
        sql: str,
        params: Dict[str, str],
        workgroup: str,
        output_s3: str,
        database: str,
    ) -> str:
        """Starts an Athena query execution with rudimentary parameter binding."""

        query_string_with_params = sql
        for key, value in params.items():
            query_string_with_params = query_string_with_params.replace(f":{key}", f"'{value}'")

        response = self.athena.start_query_execution(
            QueryString=query_string_with_params,
            QueryExecutionContext={"Database": database},
            ResultConfiguration={"OutputLocation": output_s3},
            WorkGroup=workgroup,
        )
        return response["QueryExecutionId"]

    def wait_query(
        self,
        query_execution_id: str,
        poll_interval_seconds: int = 2,
        timeout_seconds: int = 600,
    ) -> Dict[str, Any]:
        """Polls the status of an Athena query until completion or timeout."""

        start_time = time.time()
        while True:
            response = self.athena.get_query_execution(QueryExecutionId=query_execution_id)
            query_execution = response["QueryExecution"]
            status = query_execution["Status"]["State"]

            if status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                return query_execution

            if time.time() - start_time > timeout_seconds:
                self.athena.stop_query_execution(QueryExecutionId=query_execution_id)
                raise TimeoutError(
                    f"Athena query {query_execution_id} timed out after {timeout_seconds} seconds."
                )

            time.sleep(poll_interval_seconds)

    def fetch_results(
        self,
        query_execution_id: str,
        page_size: int = 1000,
    ) -> List[Dict[str, Optional[str]]]:
        """Returns Athena query results as a list of dictionaries."""

        paginator = self.athena.get_paginator("get_query_results")

        rows: List[Dict[str, Optional[str]]] = []
        column_names: List[str] = []
        first_page = True

        for page in paginator.paginate(
            QueryExecutionId=query_execution_id,
            PaginationConfig={"PageSize": page_size},
        ):
            result_set = page["ResultSet"]

            if not column_names:
                column_names = [col["Name"] for col in result_set["ResultSetMetadata"]["ColumnInfo"]]

            data_rows = result_set["Rows"]
            if first_page:
                # First row of the first page contains column headers.
                data_rows = data_rows[1:]
                first_page = False

            for row in data_rows:
                entry: Dict[str, Optional[str]] = {}
                for column_name, datum in zip(column_names, row["Data"]):
                    entry[column_name] = next(iter(datum.values()), None) if datum else None
                rows.append(entry)

        return rows
