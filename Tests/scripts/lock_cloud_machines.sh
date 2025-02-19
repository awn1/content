#! /bin/bash

poetry run python3 -u ./Tests/scripts/lock_cloud_machines.py \
  --service_account "${GCS_ARTIFACTS_KEY}" \
  --gcs_locks_path "${GCS_LOCKS_PATH}" \
  --ci_pipeline_id "${CI_PIPELINE_ID}" \
  --ci_job_id "${CI_JOB_ID}" \
  --cloud_servers_path "${CLOUD_SAAS_SERVERS_PATH}" \
  --flow_type "${CLOUD_MACHINES_TYPE}" \
  --server_type "${SERVER_TYPE}" \
  --gitlab_status_token "${GITLAB_API_TOKEN_CONTENT}" \
  --lock_machine_name "${LOCK_MACHINE_NAME}" \
  --lock_timeout "${CLOUD_MACHINES_TIMEOUT}" \
  --machines-count-timeout-condition "${CLOUD_MACHINES_COUNT_TIMEOUT_CONDITION}" \
  --machines-count-minimum-condition "${CLOUD_MACHINES_COUNT_MINIMUM_CONDITION}" \
  --response_machine "${ARTIFACTS_FOLDER}/locked_machines_list.txt" \
  --github_token "${GITHUB_TOKEN}" \
  --branch_name "${CI_COMMIT_REF_NAME}" \
  --name-mapping_path "${CI_PROJECT_DIR}/config/name_mapping.json" \
  --chosen_machine_path "${ARTIFACTS_FOLDER}/is_chosen_machine.txt"
