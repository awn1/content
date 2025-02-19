#!/usr/bin/env bash

# exit on errors
set -e

DEV_BUCKET="$1"
PROD_BUCKET="$2"

SOURCE_PATH="upload-flow/builds/test_groups_file/${CI_PIPELINE_ID}/content"
# ====== UPDATING TESTING BUCKET ======
echo "Copying production bucket files at: gs://$PROD_BUCKET/content to dev bucket at path: gs://$DEV_BUCKET/$SOURCE_PATH"
gcloud storage cp -r "gs://${PROD_BUCKET}/content/" "gs://${DEV_BUCKET}/${SOURCE_PATH}" --quiet >>"${ARTIFACTS_FOLDER}/logs/${DEV_BUCKET}-deploy_groups_file.log" 2>&1

echo "Finished copying successfully."
