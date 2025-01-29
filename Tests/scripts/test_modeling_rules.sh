#!/usr/bin/env bash

function exit_on_error {
  if [ "${1}" -ne 0 ]; then
    echo "ERROR: ${2}, exiting with code ${1}" 1>&2
    exit "${1}"
  fi
}

if [[ "${SERVER_TYPE}" != "XSIAM" ]]; then
  echo "This script is only supported for XSIAM server type"
  exit 0
fi

MODELING_RULES_RESULTS_FILE_NAME="${ARTIFACTS_FOLDER_INSTANCE}/test_modeling_rules_report.xml"

function write_empty_test_results_file() {
  cat <<EOF >"${MODELING_RULES_RESULTS_FILE_NAME}"
<?xml version='1.0' encoding='utf-8'?>
<testsuites />
EOF
}

# Parsing the user inputs.
generate_empty_results_file="false"
while [[ "$#" -gt 0 ]]; do
  case $1 in
  --generate-empty-result-file)
    generate_empty_results_file="true"
    shift
    ;;
  *) # unknown option.
    shift ;;
  esac
done

if [[ "${generate_empty_results_file,,}" == "true" ]]; then
  write_empty_test_results_file
  exit 0
fi

if [[ ! -s "${ARTIFACTS_FOLDER_SERVER_TYPE}/modeling_rules_to_test.json" ]]; then
  echo "No modeling rules were marked for testing during test collection - writing empty junit file to ${MODELING_RULES_RESULTS_FILE_NAME}"
  write_empty_test_results_file
  exit 0
fi

echo "Found modeling rules to test, starting test modeling rules"
exit_code=0
CURRENT_DIR=$(pwd)
echo "CURRENT_DIR: ${CURRENT_DIR}"
echo "IS_NIGHTLY: ${IS_NIGHTLY}"

if [ -n "${CLOUD_CHOSEN_MACHINE_IDS}" ]; then

  echo "Getting cloud machine details for: ${CLOUD_CHOSEN_MACHINE_IDS}"
  python Tests/scripts/get_cloud_machines_details.py --cloud_machine_ids "${CLOUD_CHOSEN_MACHINE_IDS}" >"cloud_machines_details.json"
  exit_on_error $? "Failed to get cloud machine details"
  echo "Saved cloud machine details for: ${CLOUD_CHOSEN_MACHINE_IDS} under 'cloud_machines_details.json'"

  echo "Testing Modeling Rules - Results will be saved to ${MODELING_RULES_RESULTS_FILE_NAME}"

  demisto-sdk modeling-rules test --non-interactive \
    --junit-path="${MODELING_RULES_RESULTS_FILE_NAME}" \
    --cloud_servers_path "${CLOUD_SAAS_SERVERS_PATH}" \
    --cloud_servers_api_keys "cloud_machines_details.json" \
    --machine_assignment "${ARTIFACTS_FOLDER_SERVER_TYPE}/machine_assignment.json" \
    --branch_name "${CI_COMMIT_BRANCH}" \
    --build_number "${CI_PIPELINE_ID}" \
    --artifacts_bucket "${GCS_ARTIFACTS_BUCKET}" \
    --nightly "${IS_NIGHTLY}"
  exit_code=$?

  if [ -n "${FAIL_ON_ERROR}" ]; then
    if [ "${exit_code}" -eq 0 ]; then
      echo "Finish running test modeling rules without errors on instance role: ${INSTANCE_ROLE}, server type:${SERVER_TYPE} - exiting with code ${exit_code}"
    else
      echo "Finish running test modeling rules with errors on instance role: ${INSTANCE_ROLE}, server type:${SERVER_TYPE} - exiting with code ${exit_code}"
    fi
    exit "${exit_code}"
  else
    echo "Finish running test modeling rules, error handling will be done on the results job, exiting with code 0"
    exit 0
  fi

else
  write_empty_test_results_file
  exit_on_error 1 "No machines were chosen"
fi
