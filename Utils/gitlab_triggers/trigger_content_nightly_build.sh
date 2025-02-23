#!/usr/bin/env bash
# This script triggers Content Nightly in gitlab-CI.

# For this script to work you will need to use a trigger token (see here for more about that: https://docs.gitlab.com/ee/ci/triggers/#create-a-pipeline-trigger-token)

# This script requires the gitlab-ci trigger token. The branch to run against is an optional second parameter (the default is the current branch). The Slack channel to send messages to is an optional third parameter (the default is the 'dmst-build-test')

# Ways to run this script are:
# trigger_content_nightly_build.sh -ct <trigger-token> [-b <branch-name> -ch <slack-channel-name>]
if [ "$#" -lt "1" ]; then
  echo "Usage:
  $0 -ct <token>

  [-ct, --ci-token]                         The ci gitlab trigger token.
  [-b, --branch]                            The content repo branch name. Default is the current branch name.
  [-ch, --slack-channel]                    A Slack channel to send notifications to. Default is dmst-build-test.
  [-sr, --sdk-ref]                          The demisto-sdk repo branch to run nightly SDK build with. Default is master.
  [-ib, --infra-branch]                     The infra repo branch name. Default is the current branch name.
  [-sn, --scheduled-nightly]                Whether this build is a scheduled nightly build.
  [-tmr, --test-modeling-rule-jira-tickets] Whether to enable test modeling rule jira tickets creation.
  [-tpr, --test-playbooks-jira-tickets]     Whether to enable test playbooks jira tickets creation.
  [-tuc, --test-use-case-jira-tickets]     Whether to enable test use case jira tickets creation.
  [-nn, --native-nightly]                   Whether this build is a native nightly build.
  "
  echo "Get the trigger token from here https://vault.paloaltonetworks.local/home#R2VuZXJpY1NlY3JldERldGFpbHM6RGF0YVZhdWx0OmIyMzJiNDU0LWEzOWMtNGY5YS1hMTY1LTQ4YjRlYzM1OTUxMzpSZWNvcmRJbmRleDowOklzVHJ1bmNhdGVk" # disable-secrets-detection
  exit 1
fi

_branch="$(git branch --show-current)"
_infra_branch="$(git branch --show-current)"
_scheduled_nightly="false"
_slack_channel="dmst-build-test"
TEST_MODELING_RULE_JIRA_TICKETS="false"
TEST_USE_CASE_JIRA_TICKETS="false"
TEST_PLAYBOOKS_JIRA_TICKETS="false"
_sdk_ref="${SDK_REF:-master}"
_override_sdk_ref="${DEMISTO_SDK_NIGHTLY:-false}"
_is_nightly="true"
_is_native_nightly="false"

# Parsing the user inputs.

while [[ "$#" -gt 0 ]]; do
  case $1 in

  -ct | --ci-token)
    _ci_token="${2}"
    shift
    shift
    ;;

  -b | --branch)
    _branch="${2}"
    shift
    shift
    ;;
  -ib | --infra-branch)
    _infra_branch="${2}"
    shift
    shift
    ;;

  -sn | --scheduled-nightly)
    _scheduled_nightly="true"
    shift
    ;;

  -ch | --slack-channel)
    _slack_channel="${2}"
    shift
    shift
    ;;

  -sr | --sdk-ref)
    _sdk_ref="${2}"
    _override_sdk_ref="true"
    shift
    shift
    ;;

  -tmr | --test-modeling-rule-jira-tickets)
    TEST_MODELING_RULE_JIRA_TICKETS="true"
    shift
    ;;

  -tuc | --test-use-case-jira-tickets)
    TEST_USE_CASE_JIRA_TICKETS="true"
    shift
    ;;

  -tpr | --test-playbooks-jira-tickets)
    TEST_PLAYBOOKS_JIRA_TICKETS="true"
    shift
    ;;
  -nn | --native-nightly)
    _is_native_nightly="true" _is_nightly="false"
    shift
    ;;

  *) # unknown option.
    shift ;;
  esac
done

if [ -z "${_ci_token}" ]; then
  echo "You must provide a ci token."
  exit 1
fi

CONTENT_PROJECT_ID=${CONTENT_PROJECT_ID:-1061}
CI_SERVER_URL=${CI_SERVER_URL:-https://gitlab.xdr.pan.local} # disable-secrets-detection

export BUILD_TRIGGER_URL="${CI_SERVER_URL}/api/v4/projects/${CONTENT_PROJECT_ID}/trigger/pipeline"

curl "$BUILD_TRIGGER_URL" --form "ref=${_branch}" --form "token=${_ci_token}" \
  --form "variables[INFRA_BRANCH]=${_infra_branch}" \
  --form "variables[SCHEDULED_NIGHTLY]=${_scheduled_nightly}" \
  --form "variables[SDK_REF]=${_sdk_ref}" \
  --form "variables[OVERRIDE_SDK_REF]=${_override_sdk_ref}" \
  --form "variables[IS_NIGHTLY]=${_is_nightly}" \
  --form "variables[IS_NATIVE_NIGHTLY]=${_is_native_nightly}" \
  --form "variables[TEST_MODELING_RULE_JIRA_TICKETS]=${TEST_MODELING_RULE_JIRA_TICKETS}" \
  --form "variables[TEST_USE_CASE_JIRA_TICKETS]=${TEST_USE_CASE_JIRA_TICKETS}" \
  --form "variables[TEST_PLAYBOOKS_JIRA_TICKETS]=${TEST_PLAYBOOKS_JIRA_TICKETS}" \
  --form "variables[SLACK_CHANNEL]=${_slack_channel}" \
  --form "variables[BRANCH]=${_branch}" \
  --silent | jq
