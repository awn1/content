#!/usr/bin/env bash
# ====== BUILD CONFIGURATION ======

if [[ -z "$3" ]]; then
  MARKETPLACE_TYPE="xsoar" # The default is "marketplace-dist"
else
  MARKETPLACE_TYPE=$3
fi

BUILD_BUCKET_PATH="content/builds/$CI_COMMIT_BRANCH/$CI_PIPELINE_ID"
BUILD_BUCKET_PACKS_DIR_PATH="$BUILD_BUCKET_PATH/content/packs"
BUILD_BUCKET_PACKS_DIR_FULL_PATH="$GCS_BUILD_BUCKET/$BUILD_BUCKET_PACKS_DIR_PATH"

echo "Handling versions-metadata file updates."
python3 ./Tests/Marketplace/upload_server_versions_metadata.py -pa "${ARTIFACTS_FOLDER_SERVER_TYPE}"
echo "Finished updating the versions-metadata file"

if [ -f "${ARTIFACTS_FOLDER_SERVER_TYPE}/versions-metadata.json" ]; then
  echo "Uploading versions-metadata.json."
  gsutil cp -z json "${ARTIFACTS_FOLDER_SERVER_TYPE}/versions-metadata.json" "gs://$BUILD_BUCKET_PACKS_DIR_FULL_PATH" >>"${ARTIFACTS_FOLDER_SERVER_TYPE}/logs/upload_versions_core_files_gsutil.log" 2>&1
  echo "Successfully uploaded versions-metadata.json."
else
  echo "No versions-metadata.json file, skipping uploading."
fi

echo "Finished updating content packs successfully."
