#!/usr/bin/env bash

# The functions below are copied from demisto/content/Tests/scripts/download_conf_repos.sh
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

clone_repository() {
  local host=$1
  local user=$2
  local token=$3
  local repo_name=$4
  local branch=$5
  local retry_count=$6
  local sleep_time=${7:-10}  # default sleep time is 10 seconds.
  local exit_code=0
  local i=1
  echo -e "${GREEN}Cloning ${repo_name} from ${host} branch:${branch} with ${retry_count} retries${NC}"
  if [ -z "${user}" ] && [ -z "${token}" ]; then
    user_info=""
  else
    user_info="${user}:${token}@"
    # If either user or token is not empty, then we need to add them to the url.
  fi
  for ((i=1; i <= retry_count; i++)); do
    git clone --depth=1 "https://${user_info}${host}/${repo_name}.git" --branch "${branch}" && exit_code=0 && break || exit_code=$?
    if [ ${i} -ne "${retry_count}" ]; then
      echo -e "${RED}Failed to clone ${repo_name} with branch:${branch}, exit code:${exit_code}, sleeping for ${sleep_time} seconds and trying again${NC}"
      sleep "${sleep_time}"
    else
      echo -e "${RED}Failed to clone ${repo_name} with branch:${branch}, exit code:${exit_code}, exhausted all ${retry_count} retries${NC}"
      break
    fi
  done
  return ${exit_code}
}

clone_repository_with_fallback_branch() {
  local host=$1
  local user=$2
  local token=$3
  local repo_name=$4
  local branch=$5
  local retry_count=$6
  local sleep_time=${7:-10}  # default sleep time is 10 seconds.
  local fallback_branch="${8:-master}"

  # Check if branch exists in the repository.
  echo -e "${GREEN}Checking if branch ${branch} exists in ${repo_name}${NC}"
  if [ -z "${user}" ] && [ -z "${token}" ]; then
    user_info=""
  else
    # If either user or token is not empty, then we need to add them to the url.
    user_info="${user}:${token}@"
  fi
  git ls-remote --exit-code --quiet --heads "https://${user_info}${host}/${repo_name}.git" "refs/heads/${branch}" 1>/dev/null 2>&1
  local branch_exists=$?

  if [ "${branch_exists}" -ne 0 ]; then
    echo -e "${RED}Branch ${branch} does not exist in ${repo_name}, defaulting to ${fallback_branch}${NC}"
    local exit_code=1
  else
    echo -e "${GREEN}Branch ${branch} exists in ${repo_name}, trying to clone${NC}"
    clone_repository "${host}" "${user}" "${token}" "${repo_name}" "${branch}" "${retry_count}" "${sleep_time}"
    local exit_code=$?
    if [ "${exit_code}" -ne 0 ]; then
      echo -e "${RED}Failed to clone ${repo_name} with branch:${branch}, exit code:${exit_code}${NC}"
    fi
  fi
  if [ "${exit_code}" -ne 0 ]; then
    # Trying to clone from fallback branch.
    echo -e "${RED}Trying to clone repository:${repo_name} with fallback branch ${fallback_branch}!${NC}"
    clone_repository "${host}" "${user}" "${token}" "${repo_name}" "${fallback_branch}" "${retry_count}" "${sleep_time}"
    local exit_code=$?
    if [ ${exit_code} -ne 0 ]; then
      echo -e "${RED}ERROR: Failed to clone ${repo_name} with fallback branch:${fallback_branch}, exit code:${exit_code}, exiting!${NC}"
      exit ${exit_code}
    else
      echo -e "${GREEN}Successfully cloned ${repo_name} with fallback branch:${fallback_branch}${NC}"
      return 0
    fi
  else
    echo -e "${GREEN}Successfully cloned ${repo_name} with branch:${branch}${NC}"
    return 0
  fi
}


NAMESPACE_DIR="${CI_BUILDS_DIR}/${CI_PROJECT_NAMESPACE}"
# Clean prev content repo dir.
if [ -d "${NAMESPACE_DIR}" ]; then
  cd "${NAMESPACE_DIR}" || exit 1
  if [ -d "${NAMESPACE_DIR}/content" ]; then
    echo "cleaning prev content repo dir"
    rm -rf "${NAMESPACE_DIR}/content"
  fi
else
  echo "creating xsoar dir"
  mkdir -p "${NAMESPACE_DIR}"
fi

echo "Getting content from branch:${CI_COMMIT_REF_NAME}, with fallback to master"

clone_repository_with_fallback_branch "github.com" "" "" "demisto/content" "${CI_COMMIT_REF_NAME}" 3 10 "master"
