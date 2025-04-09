#!/bin/bash

function parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
    --origin-bucket-list=*)
      origin_buckets="${1#*=}"
      shift
      ;;
    --prod-bucket-list=*)
      prod_buckets="${1#*=}"
      shift
      ;;
    *)
      echo "Unknown parameter: $1"
      exit 1
      ;;
    esac
  done

  if [[ -z "$origin_buckets" || -z "$prod_buckets" ]]; then
    echo "Usage: $0 -origin=<comma-separated-origin-buckets> --prod=<comma-separated-prod-buckets>"
    exit 1
  fi
}

function compare_revision() {
  local IFS=','
  read -ra bucket_list_origin <<<"$origin_buckets"
  read -ra bucket_list_prod <<<"$prod_buckets"
  json_file_path="/content/packs/index.json"

  # Compare the revision fields for each pair of buckets
  for ((i = 0; i < ${#bucket_list_origin[@]}; i++)); do
    bucket1="${bucket_list_origin[$i]}"
    bucket2="${bucket_list_prod[$i]}"

    echo "Comparing revisions for $bucket1 and $bucket2"

    gsutil cp "gs://$bucket1$json_file_path" $ARTIFACTS_FOLDER/sync/origin_index.json || {
      echo "Failed to copy from $bucket1"
      exit 1
    }
    gsutil cp "gs://$bucket2$json_file_path" $ARTIFACTS_FOLDER/sync/prod_index.json || {
      echo "Failed to copy from $bucket2"
      exit 1
    }

    revision_origin=$(jq -r '.revision' $ARTIFACTS_FOLDER/sync/origin_index.json)
    revision_prod=$(jq -r '.revision' $ARTIFACTS_FOLDER/sync/prod_index.json)

    # Compare the revisions
    if [ "$revision_origin" = "$revision_prod" ]; then
      echo "Revisions are the same: $revision_origin"
    else
      echo "Revisions are different: $revision_origin (in $bucket_list_origin) vs $revision_prod (in $bucket_list_prod)"
      exit 1
    fi

    echo
  done
}

parse_args "$@"
compare_revision
