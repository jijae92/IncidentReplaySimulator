#!/bin/bash
set -euo pipefail

# --- Configuration ---

# Get the absolute path of the script's directory
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# AWS Region and Stack Name (update if necessary, or use environment variables)
AWS_REGION=${AWS_REGION:-"ap-northeast-2"}
STACK_NAME=${STACK_NAME:-"IncidentReplaySimulator"}

# Function Logical IDs from template.yaml
INGEST_FUNCTION="IngestReplayLogFunction"
ORCHESTRATOR_FUNCTION="ReplayOrchestratorFunction"
DETECTOR_FUNCTION="DetectorAdapterStubFunction"
REPORTER_FUNCTION="ReporterFunction"

# Event file paths (relative to the script directory)
INGEST_EVENT="events/ingest.json"
REPLAY_EVENT="events/replay.json"
DETECTOR_EVENT="events/detector.json"
REPORT_EVENT="events/report.json"

# --- Helper Functions ---

# Get the physical ID of a Lambda function from the logical ID
get_function_name() {
  local logical_id="$1"
  local physical_id
  physical_id=$(aws cloudformation describe-stack-resource --stack-name "$STACK_NAME" --logical-resource-id "$logical_id" --query 'StackResourceDetail.PhysicalResourceId' --output text --region "$AWS_REGION" 2>/dev/null)
  
  if [ -z "$physical_id" ]; then
    echo "[ERROR] Failed to get physical name for function '$logical_id'. Please check the stack name and region." >&2
    exit 1
  fi
  echo "$physical_id"
}

# Invoke a Lambda function and handle the response
invoke_lambda() {
  local function_name="$1"
  local event_file="$2"
  local output_file="/tmp/lambda_output.json"
  local event_payload

  event_payload=$(cat "$event_file")

  echo "Invoking $function_name with payload from $event_file..."
  aws lambda invoke --function-name "$function_name" --payload "$event_payload" "$output_file" --cli-binary-format raw-in-base64-out --region "$AWS_REGION"

  if grep -q "FunctionError" "$output_file"; then
    echo "  [ERROR] Lambda function execution failed. Response:" >&2
    cat "$output_file" >&2
    exit 1
  else
    echo "  [SUCCESS] Lambda function executed successfully."
    jq . < "$output_file"
    echo ""
  fi
}

# --- Main Script ---

echo "--- Starting End-to-End Scenario Test for stack '$STACK_NAME' in region '$AWS_REGION' ---"

# 0. Verify Stack Status
echo "Verifying stack '$STACK_NAME' status..."
STACK_STATUS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].StackStatus" --output text --region "$AWS_REGION" 2>/dev/null) || {
  echo "[ERROR] Failed to get status for stack '$STACK_NAME'. Does it exist in region '$AWS_REGION'?" >&2
  exit 1
}

if [[ "$STACK_STATUS" != "CREATE_COMPLETE" && "$STACK_STATUS" != "UPDATE_COMPLETE" ]]; then
  echo "[ERROR] Stack '$STACK_NAME' is not in a valid state for testing. Current state: $STACK_STATUS" >&2
  exit 1
fi
echo "  [SUCCESS] Stack is in a valid state ($STACK_STATUS)."

# 1. Get physical function names
INGEST_FUNCTION_NAME=$(get_function_name "$INGEST_FUNCTION")
ORCHESTRATOR_FUNCTION_NAME=$(get_function_name "$ORCHESTRATOR_FUNCTION")
DETECTOR_FUNCTION_NAME=$(get_function_name "$DETECTOR_FUNCTION")
REPORTER_FUNCTION_NAME=$(get_function_name "$REPORTER_FUNCTION")

# 2. Get bucket names from stack outputs
RESULTS_BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='ResultsBucket'].OutputValue" --output text --region "$AWS_REGION")

if [ -z "$RESULTS_BUCKET" ]; then
  echo "[ERROR] Could not retrieve ResultsBucket from stack '$STACK_NAME' outputs." >&2
  exit 1
fi
echo "Found Results Bucket: $RESULTS_BUCKET"

# 3. Invoke functions sequentially
invoke_lambda "$INGEST_FUNCTION_NAME" "$SCRIPT_DIR/$INGEST_EVENT"

# Invoke orchestrator and capture its output to get the query execution ID
invoke_lambda "$ORCHESTRATOR_FUNCTION_NAME" "$SCRIPT_DIR/$REPLAY_EVENT"
QUERY_EXECUTION_ID=$(jq -r .body /tmp/lambda_output.json | jq -r .query_execution_id)

if [ -z "$QUERY_EXECUTION_ID" ] || [ "$QUERY_EXECUTION_ID" == "null" ]; then
    echo "[ERROR] Could not extract query_execution_id from orchestrator output." >&2
    exit 1
fi
echo "Extracted QueryExecutionId: $QUERY_EXECUTION_ID"

# Update the report event with the real QueryExecutionId
UPDATED_REPORT_EVENT="/tmp/report_event.json"
cp "$SCRIPT_DIR/$REPORT_EVENT" "$UPDATED_REPORT_EVENT"
sed -i "s/a1b2c3d4-e5f6-7890-1234-567890abcdef/$QUERY_EXECUTION_ID/g" "$UPDATED_REPORT_EVENT"

invoke_lambda "$DETECTOR_FUNCTION_NAME" "$SCRIPT_DIR/$DETECTOR_EVENT"
invoke_lambda "$REPORTER_FUNCTION_NAME" "$UPDATED_REPORT_EVENT"

# 4. Verify success criteria
echo "--- Verifying Success Criteria ---"

# Give some time for files to appear in S3
sleep 5

# Check for query results
QUERY_RESULTS_PATH="irs/queries/${QUERY_EXECUTION_ID}.csv"
echo "Checking for query results file: s3://${RESULTS_BUCKET}/${QUERY_RESULTS_PATH}"
if aws s3api head-object --bucket "$RESULTS_BUCKET" --key "$QUERY_RESULTS_PATH" --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "  [SUCCESS] Query results file found."
else
  echo "  [FAILURE] Query results file NOT found." >&2
  exit 1
fi

# Check for metrics file
METRICS_PATH="irs/metrics/metrics_${QUERY_EXECUTION_ID}.json"
echo "Checking for metrics file: s3://${RESULTS_BUCKET}/${METRICS_PATH}"
if aws s3api head-object --bucket "$RESULTS_BUCKET" --key "$METRICS_PATH" --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "  [SUCCESS] Metrics file found."
else
  echo "  [FAILURE] Metrics file NOT found." >&2
  exit 1
fi

# SNS check is manual, but we confirmed the reporter function succeeded.

echo "
--- End-to-End Test Scenario Completed Successfully ---"
exit 0
