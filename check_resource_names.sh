#!/bin/bash
set -euo pipefail

# Default AWS region
REGION="ap-northeast-2"

# --- Helper Functions ---

# Check if an S3 bucket exists and if it's owned by the current account
check_bucket () {
  local name="$1"
  if [ -z "$name" ]; then return 0; fi # Skip if name is empty

  echo "Checking S3 bucket: $name"
  if aws s3api list-buckets --query 'Buckets[].Name' --output text --region "$REGION" | tr '\t' '\n' | grep -qx "$name"; then
    echo "  [OWNED] S3 bucket '$name' exists and is owned by your account."
  else
    # Check if the bucket name is taken globally
    if aws s3api head-bucket --bucket "$name" --region "$REGION" >/dev/null 2>&1; then
      echo "  [TAKEN] S3 bucket name '$name' is taken globally (not yours)."
      return 2 # Indicate that the name is taken
    else
      echo "  [FREE] S3 bucket name '$name' seems available."
    fi
  fi
}

# Check if a Glue Database exists
check_glue () {
  local db_name="$1"
  if [ -z "$db_name" ]; then return 0; fi # Skip if name is empty

  echo "Checking Glue Database: $db_name"
  if aws glue get-database --name "$db_name" --region "$REGION" >/dev/null 2>&1; then
    echo "  [EXISTS] Glue Database '$db_name' found."
  else
    echo "  [MISSING] Glue Database '$db_name' not found."
  fi
}

# Check if an Athena WorkGroup exists
check_athena_wg () {
  local wg_name="$1"
  if [ -z "$wg_name" ]; then return 0; fi # Skip if name is empty

  echo "Checking Athena WorkGroup: $wg_name"
  if aws athena list-work-groups --region "$REGION" --query 'WorkGroups[].Name' --output text | tr '\t' '\n' | grep -qx "$wg_name"; then
    echo "  [EXISTS] Athena WorkGroup '$wg_name' found."
  else
    echo "  [MISSING] Athena WorkGroup '$wg_name' not found."
  fi
}

# --- Main Script Logic ---

echo "--- Pre-deployment Name Conflict Check ---"

# Get AWS Account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$AWS_ACCOUNT_ID" ]; then
  echo "Error: Could not retrieve AWS Account ID. Ensure AWS CLI is configured."
  exit 1
fi

# Prompt for Stack Name and Region if not set
if [ -z "${STACK_NAME}" ]; then
  read -p "Enter CloudFormation Stack Name (e.g., IncidentReplaySimulator): " STACK_NAME
fi
if [ -z "${STACK_NAME}" ]; then
  echo "Error: Stack Name cannot be empty."
  exit 1
fi

if [ -z "${AWS_REGION}" ]; then
  read -p "Enter AWS Region (e.g., ap-northeast-2): " AWS_REGION
fi
if [ -z "${AWS_REGION}" ]; then
  echo "Error: AWS Region cannot be empty."
  exit 1
fi
REGION=$AWS_REGION # Update REGION variable for functions

# --- Extract parameters from template.yaml ---
TEMPLATE_FILE="/mnt/c/Users/User/Downloads/IncidentReplaySimulator/template.yaml"

# Check if yq is available for robust YAML parsing
if command -v yq &> /dev/null; then
  echo "Using yq for YAML parsing."
  USE_EXISTING_RESOURCES_DEFAULT=$(yq '.Parameters.UseExistingResources.Default' "$TEMPLATE_FILE")
  REPLAY_BUCKET_NAME_DEFAULT=$(yq '.Parameters.ReplayBucketName.Default' "$TEMPLATE_FILE")
  RESULTS_BUCKET_NAME_DEFAULT=$(yq '.Parameters.ResultsBucketName.Default' "$TEMPLATE_FILE")
  GLUE_DATABASE_PREFIX_DEFAULT=$(yq '.Parameters.GlueDatabasePrefix.Default' "$TEMPLATE_FILE")
  ATHENA_WORK_GROUP_PREFIX_DEFAULT=$(yq '.Parameters.AthenaWorkGroupPrefix.Default' "$TEMPLATE_FILE")
  EXISTING_REPLAY_BUCKET_NAME_DEFAULT=$(yq '.Parameters.ExistingReplayBucketName.Default' "$TEMPLATE_FILE")
  EXISTING_RESULTS_BUCKET_NAME_DEFAULT=$(yq '.Parameters.ExistingResultsBucketName.Default' "$TEMPLATE_FILE")
  EXISTING_GLUE_DATABASE_NAME_DEFAULT=$(yq '.Parameters.ExistingGlueDatabaseName.Default' "$TEMPLATE_FILE")
  EXISTING_ATHENA_WORK_GROUP_NAME_DEFAULT=$(yq '.Parameters.ExistingAthenaWorkGroupName.Default' "$TEMPLATE_FILE")
else
  echo "yq not found. Using hardcoded default parameter values. Install yq for robust parsing."
  USE_EXISTING_RESOURCES_DEFAULT="false"
  REPLAY_BUCKET_NAME_DEFAULT=""
  RESULTS_BUCKET_NAME_DEFAULT=""
  GLUE_DATABASE_PREFIX_DEFAULT="irsdb"
  ATHENA_WORK_GROUP_PREFIX_DEFAULT="irswg"
  EXISTING_REPLAY_BUCKET_NAME_DEFAULT=""
  EXISTING_RESULTS_BUCKET_NAME_DEFAULT=""
  EXISTING_GLUE_DATABASE_NAME_DEFAULT=""
  EXISTING_ATHENA_WORK_GROUP_NAME_DEFAULT=""
fi

# Use environment variables if set, otherwise use defaults from template (or hardcoded)
USE_EXISTING_RESOURCES=${USE_EXISTING_RESOURCES:-$USE_EXISTING_RESOURCES_DEFAULT}
REPLAY_BUCKET_NAME=${REPLAY_BUCKET_NAME:-$REPLAY_BUCKET_NAME_DEFAULT}
RESULTS_BUCKET_NAME=${RESULTS_BUCKET_NAME:-$RESULTS_BUCKET_NAME_DEFAULT}
GLUE_DATABASE_PREFIX=${GLUE_DATABASE_PREFIX:-$GLUE_DATABASE_PREFIX_DEFAULT}
ATHENA_WORK_GROUP_PREFIX=${ATHENA_WORK_GROUP_PREFIX:-$ATHENA_WORK_GROUP_PREFIX_DEFAULT}
EXISTING_REPLAY_BUCKET_NAME=${EXISTING_REPLAY_BUCKET_NAME:-$EXISTING_REPLAY_BUCKET_NAME_DEFAULT}
EXISTING_RESULTS_BUCKET_NAME=${EXISTING_RESULTS_BUCKET_NAME:-$EXISTING_RESULTS_BUCKET_NAME_DEFAULT}
EXISTING_GLUE_DATABASE_NAME=${EXISTING_GLUE_DATABASE_NAME:-$EXISTING_GLUE_DATABASE_NAME_DEFAULT}
EXISTING_ATHENA_WORK_GROUP_NAME=${EXISTING_ATHENA_WORK_GROUP_NAME:-$EXISTING_ATHENA_WORK_GROUP_NAME_DEFAULT}

# --- Determine Effective Resource Names ---

if [ "$USE_EXISTING_RESOURCES" == "true" ]; then
  echo "\n--- Using Existing Resources Mode ---"
  echo "Verifying existence of provided existing resources."

  check_bucket "$EXISTING_REPLAY_BUCKET_NAME"
  check_bucket "$EXISTING_RESULTS_BUCKET_NAME"
  check_glue "$EXISTING_GLUE_DATABASE_NAME"
  check_athena_wg "$EXISTING_ATHENA_WORK_GROUP_NAME"

else
  echo "\n--- Creating New Resources Mode ---"
  echo "Checking availability of proposed new resource names."

  # Replay Bucket
  if [ -z "$REPLAY_BUCKET_NAME" ]; then
    echo "Replay S3 Bucket: Will be auto-generated by CloudFormation (no name conflict check possible)."
  else
    check_bucket "$REPLAY_BUCKET_NAME"
  fi

  # Results Bucket
  if [ -z "$RESULTS_BUCKET_NAME" ]; then
    echo "Results S3 Bucket: Will be auto-generated by CloudFormation (no name conflict check possible)."
  else
    check_bucket "$RESULTS_BUCKET_NAME"
  fi

  # Glue Database
  EFFECTIVE_GLUE_DATABASE="${GLUE_DATABASE_PREFIX}-${STACK_NAME}-${AWS_REGION}"
  echo "Proposed Glue Database Name: $EFFECTIVE_GLUE_DATABASE"
  check_glue "$EFFECTIVE_GLUE_DATABASE"

  # Athena WorkGroup
  EFFECTIVE_ATHENA_WORK_GROUP="${ATHENA_WORK_GROUP_PREFIX}-${STACK_NAME}-${AWS_ACCOUNT_ID}-${AWS_REGION}"
  # Truncate if necessary (Athena WorkGroup names have a 128-character limit)
  if [ ${#EFFECTIVE_ATHENA_WORK_GROUP} -gt 128 ]; then
    echo "Warning: Proposed Athena WorkGroup name exceeds 128 characters. It will be truncated."
    EFFECTIVE_ATHENA_WORK_GROUP="${EFFECTIVE_ATHENA_WORK_GROUP:0:128}"
  fi
  echo "Proposed Athena WorkGroup Name: $EFFECTIVE_ATHENA_WORK_GROUP"
  check_athena_wg "$EFFECTIVE_ATHENA_WORK_GROUP"
fi

echo "\n--- Check Complete ---"
echo "Review the output above for any potential name conflicts or missing resources."