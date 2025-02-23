#!/usr/bin/env bash

function exit_on_error {
  if [ "${1}" -ne 0 ]; then
    echo "ERROR: ${2}, exiting with code ${1}" 1>&2
    exit "${1}"
  fi
}

TEST_USE_CASE_FILE_NAME="${ARTIFACTS_FOLDER_INSTANCE}/test_use_case_report.xml"

function write_empty_test_results_file() {
  cat <<EOF >"${TEST_USE_CASE_FILE_NAME}"
<?xml version='1.0' encoding='utf-8'?>
<testsuites />
EOF
}

push_alerts() {
  local pod_name="$1" # First argument: pod name
  shift               # Remaining argument: string representation of the Python list

  # Clean up the string to create a Bash array
  local raw_folders="$1"
  raw_folders="${raw_folders//[\[\]\'\"]/}"         # Remove brackets, quotes, and double quotes
  IFS=',' read -ra alerts_folders <<<"$raw_folders" # Split by commas into an array
  echo $raw_folders
  for folder in "${alerts_folders[@]}"; do
    folder=$(echo "$folder" | xargs) # Trim whitespace
    # Find JSON files in the folder
    json_files=($(find "$folder" -maxdepth 1 -type f -name "*.json" | sort))

    if [ ${#json_files[@]} -eq 0 ]; then
      echo "Failure: No JSON files found in the alerts folder: $folder"
      continue
    fi

    for json_file_path in "${json_files[@]}"; do
      json_file=$(basename "$json_file_path")
      destination_path="/src/$json_file"
      echo $json_file_path
      # Copy JSON file to the pod
      kubectl_cp_command="kubectl cp \"$json_file_path\" \"$pod_name:$destination_path\""
      if eval "$kubectl_cp_command"; then
        echo "Success: Copied $json_file to pod: $pod_name:$destination_path"
      else
        echo "Failure: Failed to copy $json_file to pod."
        continue
      fi

      # Run Python script inside the pod
      python_command="python ./src/secdo/support/alert/alert_from_original_json.py $destination_path 1 False"
      kexec_command="kubectl exec -it $pod_name -- $python_command"
      output=$(eval "$kexec_command" 2>&1)
      exit_code=$?

      if [ $exit_code -eq 0 ]; then
        last_line=$(echo "$output" | tail -n 1)
        if [[ "$last_line" == *"Done!"* ]]; then
          echo "Success: Script completed for $json_file with message: $last_line"
        elif [[ "$last_line" == *"PermissionDenied"* ]]; then
          echo "Failure: Script encountered permission issue for $json_file with message: $last_line"
        else
          echo "Failure: Script completed for $json_file with last output: $last_line"
        fi
      else
        echo "Failure: Script execution failed for $json_file with error: $output"
      fi
    done
  done
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

if [[ "${SERVER_TYPE}" != "XSIAM" ]]; then
  echo "This script is only supported for XSIAM server type"
  exit 0
fi

if [[ "${generate_empty_results_file,,}" == "true" ]]; then
  write_empty_test_results_file
  exit 0
fi

if [[ ! -s "${ARTIFACTS_FOLDER_SERVER_TYPE}/test_use_cases_to_test.json" ]]; then
  echo "No test use cases were marked for testing during test collection - writing empty junit file to ${TEST_USE_CASE_FILE_NAME}"
  write_empty_test_results_file
  exit 0
fi

echo "Found test use cases, starting test use case flow"
exit_code=0
CURRENT_DIR=$(pwd)
echo "CURRENT_DIR: ${CURRENT_DIR}"
echo "IS_NIGHTLY: ${IS_NIGHTLY}"

if [ -n "${CLOUD_CHOSEN_MACHINE_IDS}" ]; then

  echo "Getting cloud machine details for: ${CLOUD_CHOSEN_MACHINE_IDS}"
  python Tests/scripts/get_cloud_machines_details.py --cloud_machine_ids "${CLOUD_CHOSEN_MACHINE_IDS}" >"cloud_machines_details.json"
  exit_on_error $? "Failed to get cloud machine details"
  echo "Saved cloud machine details for: ${CLOUD_CHOSEN_MACHINE_IDS} under 'cloud_machines_details.json'"

  echo "Creating alerts from alerts folder in path Utils/alerts"
  # Run the Python script and store the output in a variable
  test_data_folders=$(poetry run python Tests/scripts/extract_test_use_case_data.py --machine_assignment "${ARTIFACTS_FOLDER_SERVER_TYPE}/machine_assignment.json" \
    --selected_machine "${CLOUD_CHOSEN_MACHINE_IDS}")

  if [ ${#test_data_folders[@]} -eq 0 ]; then
    # Use the test_data_folders variable as needed
    echo "Test Data Folders: $test_data_folders"

    echo "Pushing alerts into xsiam"

    echo "Getting cluster"
    cluster_info=$(gcloud container clusters list --project ${CLOUD_CHOSEN_MACHINE_IDS} --format json)

    echo "Extract first cluster's name and zone"
    cluster_name=$(echo "$cluster_info" | jq -r '.[0].name')
    cluster_zone=$(echo "$cluster_info" | jq -r '.[0].zone')

    echo "Running get creds"
    gcloud container clusters get-credentials $cluster_name --zone $cluster_zone --project ${CLOUD_CHOSEN_MACHINE_IDS}

    echo "Setting project"
    kubectl config set-context --current --namespace=xdr-st

    echo "Getting first API pod"
    pod_name=$(kubectl get pods --sort-by=.metadata.creationTimestamp | grep agent-api | awk '{print $1}' | head -n 1)
    if [ -n "$pod_name" ]; then
      echo "Used pod for pushing alerts is: $pod_name"
      push_alerts "$pod_name" "$test_data_folders"
    else
      echo "No matching pods found."
    fi
  else
    echo "No test data folders found. Skipping subsequent commands."
  fi

  echo "Test Use Case - Results will be saved to ${TEST_USE_CASE_FILE_NAME}"

  demisto-sdk test-use-case \
    --junit-path="${TEST_USE_CASE_FILE_NAME}" \
    --service_account "${GCS_ARTIFACTS_KEY}" \
    --cloud_servers_path "${CLOUD_SAAS_SERVERS_PATH}" \
    --cloud_servers_api_keys "cloud_machines_details.json" \
    --machine_assignment "${ARTIFACTS_FOLDER_SERVER_TYPE}/machine_assignment.json" \
    --build_number "${CI_PIPELINE_ID}" \
    --artifacts_bucket "${GCS_ARTIFACTS_BUCKET}" \
    --nightly "${IS_NIGHTLY}" \
    --project_id "${CLOUD_CHOSEN_MACHINE_IDS}"
  exit_code=$?

  if [ -n "${FAIL_ON_ERROR}" ]; then
    if [ "${exit_code}" -eq 0 ]; then
      echo "Finish running test use case without errors on instance role: ${INSTANCE_ROLE}, server type:${SERVER_TYPE} - exiting with code ${exit_code}"
    else
      echo "Finish running test use case with errors on instance role: ${INSTANCE_ROLE}, server type:${SERVER_TYPE} - exiting with code ${exit_code}"
    fi
    exit "${exit_code}"
  else
    echo "Finish running test use case, error handling will be done on the results job, exiting with code 0"
    exit 0
  fi

else
  write_empty_test_results_file
  exit_on_error 1 "No machines were chosen"
fi
