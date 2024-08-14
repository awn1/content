#!/usr/bin/env bash

if [ "$#" -lt "1" ]; then
  echo "Usage:
  $0 -ct <token>
  -ct, --ci-token         The ci token.
  [-cb, --content-branch] The content repo branch name. Default is the current branch.
  [-ib, --infra-branch]   The infra repo branch name. Default is the current branch.
  [-ch, --slack-channel]  A Slack channel to send notifications to. Default is dmst-bucket-upload.
  [-sr, --sdk-ref]        The demisto-sdk repo branch to run this build with.
  "
  exit 1
fi
_content_branch=""
_infra_branch=""
_sdk_ref="${SDK_REF:-master}"
_override_sdk_ref="${DEMISTO_SDK_NIGHTLY:-false}"

while [[ "$#" -gt 0 ]]; do
  case $1 in

  -ct|--ci-token) _ci_token="$2"
    shift
    shift;;

  -cb|--content-branch) _content_branch="$2"
    shift
    shift;;

  -ib|--infra-branch) _infra_branch="$2"
    shift
    shift;;

  -ch|--slack-channel) _slack_channel="$2"
    shift
    shift;;

  -sr|--sdk-ref)
    _sdk_ref="${2}"
    _override_sdk_ref="true"
    shift
    shift;;

  *)    # unknown option.
    echo "Unknown parameter passed: $1"
    exit 1;;
  esac
done

if [ -z "${_ci_token}" ]; then
    echo "You must provide a ci token."
    exit 1
fi

if [ -z "${_content_branch}" ]; then
  echo "You must provide a content branch."
  exit 1
fi

if [ -z "${_infra_branch}" ]; then
  echo "You must provide an infra branch."
  exit 1
fi

CONTENT_PROJECT_ID=${CONTENT_PROJECT_ID:-1061}
CI_SERVER_URL=${CI_SERVER_URL:-https://gitlab.xdr.pan.local} # disable-secrets-detection

export BUILD_TRIGGER_URL="${CI_SERVER_URL}/api/v4/projects/${CONTENT_PROJECT_ID}/trigger/pipeline"

curl --request POST \
  --form token="${_ci_token}" \
  --form ref="${_content_branch}" \
  --form "variables[DEMISTO_SDK_NIGHTLY]=true" \
  --form "variables[SLACK_CHANNEL]=${_slack_channel}" \
  --form "variables[SDK_REF]=${_sdk_ref}" \
  --form "variables[OVERRIDE_SDK_REF]=${_override_sdk_ref}" \
  --form "variables[INFRA_BRANCH]=${_infra_branch}" \
  "${BUILD_TRIGGER_URL}" | jq
