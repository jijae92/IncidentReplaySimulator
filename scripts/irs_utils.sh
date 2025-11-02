# Helper shell functions for interacting with IRS S3 artifacts.
# Source this file (e.g. `. scripts/irs_utils.sh`) to make the helpers available.

latest_metrics() {
  local bkt="${1:?bucket}"
  aws s3api list-objects-v2 \
    --bucket "$bkt" \
    --prefix "irs/metrics/" \
    --query 'sort_by(Contents,&LastModified)[-1].Key' \
    --output text 2>/dev/null
}

last_artifacts() {
  local bkt="${1:?bucket}" n="${2:-5}"
  aws s3api list-objects-v2 \
    --bucket "$bkt" --prefix "artifacts/" \
    --query "sort_by(Contents,&LastModified)[-${n}:][].Key" \
    --output text 2>/dev/null | tr '\t' '\n'
}

metrics_uri() {
  local bkt="${1:?bucket}" key="${2:?key}"
  printf 's3://%s/%s\n' "$bkt" "$key"
}
