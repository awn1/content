#!/usr/bin/env bash

# exit on errors
set -e

# print the bq version
bq version
gsutil --version

MAX_BAD_RECORDS=${MAX_BAD_RECORDS:-40}

SCRIPT_DIR=$(dirname ${BASH_SOURCE})
if [[ "${SCRIPT_DIR}" != /* ]]; then
  SCRIPT_DIR="$(pwd)/${SCRIPT_DIR}"
fi
echo "SCRIPT_DIR: ${SCRIPT_DIR}"

if [ -z "$BUCKET_NAME" -o -z "$LOG_TABLE" ]; then
  echo "You must specify env variables LOG_TABLE and BUCKET_NAME"
  echo "For example: BUCKET_NAME=marketplace-dist LOG_TABLE=marketplace_logs.usage ${BASH_SOURCE}"
  exit 2
fi

# BUCKET_NAME=${BUCKET_NAME:-"marketplace-dist"}
# LOG_TABLE=${LOG_TABLE:-"marketplace_logs.usage"}

echo "Using bucket: $BUCKET_NAME. Log table: $LOG_TABLE"
NO_LOGS_WERE_FOUND="CommandException: One or more URLs matched no objects."

if gsutil ls 'gs://oproxy-dev-logs/'$BUCKET_NAME'_usage_*' >logs_list.txt 2>gsutil-ls.err; then
  echo "gsutil ls completed successfully"
else
  if [ "$(cat gsutil-ls.err)" == "$NO_LOGS_WERE_FOUND" ]; then
    echo "No logs were found"
    exit 0
  else
    echo "gsutil command failed: $(cat gsutil-ls.err)"
    exit 1
  fi
fi

echo "Log files to process: $(wc -l logs_list.txt)"

# process in batches of 20 via bq.
# we first concatenate with comma seperated and then pass to xargs
# Note: on Mac we need to use -J instead of -I
REPLACE="-I"

if [ "$(uname)" = "Darwin" ]; then
  echo "Using -J for xargs (mac os)"
  REPLACE="-J"
fi

# we process in batches of 20
echo "Running bq command to load data with up to ${MAX_BAD_RECORDS} bad records allowed to skip."
i=0
cat logs_list.txt | xargs -n 20 | while read line; do
  i=$((i + 20))
  echo $line | tr ' ' ',' | xargs $REPLACE '{}' bq -q --project_id oproxy-dev load --allow_quoted_newlines --max_bad_records=$MAX_BAD_RECORDS --skip_leading_rows=1 "$LOG_TABLE" {} "$SCRIPT_DIR/cloud_storage_usage_schema_v0.json"
  echo "Done loading via bq. Moving to processed..."
  echo $line | tr ' ' '\n' | gsutil -m -q mv -I gs://oproxy-dev-logs/processed/
  echo "$(date +%H:%M:%S): total processed: $i"
done
