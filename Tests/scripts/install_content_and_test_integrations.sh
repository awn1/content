#!/usr/bin/env bash

function exit_on_error {
  if [ "${1}" -ne 0 ]; then
    echo "ERROR: ${2}, exiting with code ${1}" 1>&2
    exit "${1}"
  fi
}

echo "starting to install packs ..."

if [ -z "${INSTANCE_ROLE}" ]; then
  exit_on_error 1 "INSTANCE_ROLE not set aborting pack installation"
fi

if [[ ! -f "$GCS_MARKET_KEY" ]]; then
  exit_on_error 1 "GCS_MARKET_KEY not set aborting pack installation"
fi

if [ "${BUCKET_UPLOAD}" == "true" ]; then
  # for bucket upload we use the secrets directly without saving the file, as there are no sdk tests in this flow that require it
  SECRET_CONF_PATH=""
else
  SECRET_CONF_PATH=$(cat secret_conf_path)
fi
CONF_PATH="./Tests/conf.json"

echo "Copying test_pack_*.zip to artifacts folder:${ARTIFACTS_FOLDER}"
cp ./Tests/test_pack_*.zip "$ARTIFACTS_FOLDER" || true

echo "Starting $0 script instance role:${INSTANCE_ROLE}, Server type:${SERVER_TYPE} nightly:${IS_NIGHTLY}"

exit_code=0
if [[ "${SERVER_TYPE}" == "XSIAM" ]] || [[ "${SERVER_TYPE}" == "XSOAR SAAS" ]]; then
  if [ -n "${CLOUD_CHOSEN_MACHINE_IDS}" ]; then
    python3 ./Tests/configure_and_test_integration_instances.py -u "$USERNAME" -p "$PASSWORD" -c "$CONF_PATH" \
      --pack_ids_to_install "${ARTIFACTS_FOLDER_SERVER_TYPE}/content_packs_to_install.txt" \
      -g "${GIT_SHA1}" \
      --ami_env "${INSTANCE_ROLE}" \
      --sdk-nightly "${DEMISTO_SDK_NIGHTLY}" \
      --branch "$CI_COMMIT_BRANCH" \
      --build_number "$CI_PIPELINE_ID" \
      -sa "$GCS_MARKET_KEY" \
      --server_type "${SERVER_TYPE}" \
      --cloud_servers_path "${CLOUD_SAAS_SERVERS_PATH}" \
      --marketplace_name "$MARKETPLACE_NAME" \
      --artifacts_folder "$ARTIFACTS_FOLDER" \
      --marketplace_buckets "$GCS_MACHINES_BUCKET" \
      --machine_assignment "${ARTIFACTS_FOLDER_SERVER_TYPE}/machine_assignment.json" \
      --gsm_service_account "$GSM_SERVICE_ACCOUNT" \
      --gsm_project_id_dev "$GSM_PROJECT_ID_DEV" \
      --gsm_project_id_prod "$GSM_PROJECT_ID" \
      --github_token "$GITHUB_TOKEN" \
      --json_path_file "$SECRET_CONF_PATH"
    if [ $? -ne 0 ]; then
      exit_code=1
      echo "Failed to run configure_and_test_integration_instances.py script on ${CLOUD_CHOSEN_MACHINE_IDS}"
    fi
    exit_on_error "${exit_code}" "Finished $0 script"

    echo "Finished $0 successfully"
    exit 0
  else
    exit_on_error 1 "No machines were chosen"
  fi
elif [[ "${SERVER_TYPE}" == "XSOAR" ]]; then
  python3 ./Tests/configure_and_test_integration_instances.py -u "$USERNAME" \
    -p "$PASSWORD" \
    -c "$CONF_PATH" \
    --pack_ids_to_install "${ARTIFACTS_FOLDER_SERVER_TYPE}/content_packs_to_install.txt" -g "$GIT_SHA1" --ami_env "${INSTANCE_ROLE}" \
    --branch "$CI_COMMIT_BRANCH" --build_number "$CI_PIPELINE_ID" -sa "$GCS_MARKET_KEY" \
    --server_type "${SERVER_TYPE}" \
    --cloud_servers_path "${CLOUD_SAAS_SERVERS_PATH}" \
    --marketplace_name "$MARKETPLACE_NAME" --artifacts_folder "$ARTIFACTS_FOLDER" --marketplace_buckets "$GCS_MACHINES_BUCKET" \
    --machine_assignment "${ARTIFACTS_FOLDER_SERVER_TYPE}/machine_assignment.json" \
    --gsm_service_account "$GSM_SERVICE_ACCOUNT" \
    --gsm_project_id_dev "$GSM_PROJECT_ID_DEV" --gsm_project_id_prod "$GSM_PROJECT_ID" --github_token "$GITHUB_TOKEN" \
    --json_path_file "$SECRET_CONF_PATH"
  exit_on_error $? "Failed to run $0 script"

  echo "Finished $0 successfully"
  exit 0
else
  exit_on_error 1 "Unknown server type: ${SERVER_TYPE}"
fi
