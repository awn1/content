#!/usr/bin/env bash

E2E_TESTS_RESULTS_FILE_NAME="${ARTIFACTS_FOLDER_INSTANCE}/e2e_tests_result.xml"

function write_empty_test_results_file() {
  cat <<EOF >"${E2E_TESTS_RESULTS_FILE_NAME}"
<?xml version='1.0' encoding='utf-8'?>
<testsuites />
EOF
}

# Parsing the user inputs.
generate_empty_results_file="false"
while [[ "$#" -gt 0 ]]; do
  case "${1}" in
  --generate-empty-result-file)
    generate_empty_results_file="true"
    shift
    ;;
  *) # unknown option.
    shift
    echo "Unknown option was received: $1"
    ;;
  esac
done

if [[ "${generate_empty_results_file,,}" == "true" ]]; then
  write_empty_test_results_file
  exit 0
fi

echo "Getting cloud machine details for: ${CLOUD_CHOSEN_MACHINE_IDS}"
python Tests/scripts/get_cloud_machines_details.py --cloud_machine_ids "${CLOUD_CHOSEN_MACHINE_IDS}" >"cloud_machines_details.json"
echo "Saved cloud machine details for: ${CLOUD_CHOSEN_MACHINE_IDS} under 'cloud_machines_details.json'"

if [[ "${SERVER_TYPE}" == "XSIAM" ]]; then
  test_path="./Tests/tests_e2e/content/xsiam"
elif [[ "${SERVER_TYPE}" == "XSOAR SAAS" ]]; then
  test_path="./Tests/tests_e2e/content/xsoar_saas"
fi

if [[ -n "$test_path" ]]; then
  if [[ -z "${CLOUD_CHOSEN_MACHINE_IDS}" ]]; then
    echo "CLOUD_CHOSEN_MACHINE_IDS is not defined, exiting..."
    exit 1
  else
    exit_code=0
    IFS=', ' read -r -a CLOUD_CHOSEN_MACHINE_ID_ARRAY <<<"${CLOUD_CHOSEN_MACHINE_IDS}"
    for CLOUD_CHOSEN_MACHINE_ID in "${CLOUD_CHOSEN_MACHINE_ID_ARRAY[@]}"; do
      echo "Running end-to-end tests on ${CLOUD_CHOSEN_MACHINE_ID} from ${test_path}"
      python3 -m pytest "${test_path}" -v --cloud_machine "${CLOUD_CHOSEN_MACHINE_ID}" --cloud_servers_path "${CLOUD_SAAS_SERVERS_PATH}" --cloud_servers_api_keys "cloud_machines_details.json" --disable-warnings --junitxml="${ARTIFACTS_FOLDER_INSTANCE}/e2e_tests_result.xml" --gsm_service_account "$GSM_SERVICE_ACCOUNT" --gsm_project_id_dev "$GSM_PROJECT_ID_DEV" --gsm_project_id_prod "$GSM_PROJECT_ID" -u "$DEMISTO_USERNAME" -p "$DEMISTO_PASSWORD" --github_token "$GITHUB_TOKEN"
      # since xsiam e2e is in upload and not in nightly, we want to fail the job if its tests failed
      if [[ "${test_path}" == "./Tests/tests_e2e/content/xsiam" ]] && [[ $? -ne 0 ]]; then
        exit_code=1
      fi
    done
    echo "Finished running end-to-end tests on ${CLOUD_CHOSEN_MACHINE_IDS} with exit code ${exit_code}"
    exit "${exit_code}"
  fi
else
  echo "Not running end-to-end tests on Server Type:${SERVER_TYPE}, exiting..."
  exit 0
fi
