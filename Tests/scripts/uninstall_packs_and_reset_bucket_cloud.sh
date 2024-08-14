#!/usr/bin/env bash

function exit_on_error {
    if [ "${1}" -ne 0 ]; then
        echo "ERROR: ${2}, exiting with code ${1}" 1>&2
        exit "${1}"
    fi
}

if [[ -z "${CLOUD_CHOSEN_MACHINE_IDS}" ]]; then
  exit_on_error 1 "CLOUD_CHOSEN_MACHINE_IDS is not defined"
else
  gcloud auth activate-service-account --key-file="$GCS_MARKET_KEY" >> "${ARTIFACTS_FOLDER_INSTANCE}/logs/gcloud_auth.log" 2>&1
  exit_on_error $? "Failed to authenticate with GCS_MARKET_KEY"

  IFS=', ' read -r -a CLOUD_CHOSEN_MACHINE_ID_ARRAY <<< "${CLOUD_CHOSEN_MACHINE_IDS}"
  for CLOUD_CHOSEN_MACHINE_ID in "${CLOUD_CHOSEN_MACHINE_ID_ARRAY[@]}"; do
    echo "Copying prod bucket to ${CLOUD_CHOSEN_MACHINE_ID} bucket."
    gsutil -m cp -r "gs://$GCS_SOURCE_BUCKET/content" "gs://$GCS_MACHINES_BUCKET/${CLOUD_CHOSEN_MACHINE_ID}/" >> "${ARTIFACTS_FOLDER_INSTANCE}/logs/Copy_prod_bucket_to_cloud_machine_cleanup.log" 2>&1
    exit_on_error $? "Failed to copy prod bucket to ${CLOUD_CHOSEN_MACHINE_ID} bucket"
  done

  echo "sleeping 120 seconds"
  sleep 120


  PACKS_TO_INSTALL="${ARTIFACTS_FOLDER_SERVER_TYPE}/content_packs_to_install.txt"
  echo "PACKS_TO_INSTALL set to: ${PACKS_TO_INSTALL}"


  poetry run python3 -u ./Tests/Marketplace/search_and_uninstall_pack.py --cloud_machine "${CLOUD_CHOSEN_MACHINE_IDS}" \
    --cloud_servers_path "${CLOUD_SAAS_SERVERS_PATH}" \
    --non-removable-packs "${NON_REMOVABLE_PACKS}" --one-by-one --build-number "${CI_PIPELINE_ID}" \
    --modeling_rules_to_test_files "${ARTIFACTS_FOLDER_SERVER_TYPE}/modeling_rules_to_test.json" \
    --reset-core-pack-version "${RESET_CORE_PACK_VERSION}" --only_to_be_installed \
    --pack_ids_to_install "${PACKS_TO_INSTALL}"
  exit_on_error $? "Failed to uninstall packs from cloud machines:${CLOUD_CHOSEN_MACHINE_IDS}"

  echo "Successfully finished uninstalling packs from cloud machines"
  exit 0
fi
