#!/usr/bin/env bash
# This script triggers Demisto SDK release job in gitlab-CI.

# For this script to work you will need to use a trigger token (see here for more about that: https://docs.gitlab.com/ee/ci/triggers/#create-a-pipeline-trigger-token)

# This script requires the gitlab-ci trigger token and release version.
# The branch to run against is an optional parameter(the default is master branch).
# The Slack channel to send messages to is an optional parameter(the default is dmst-sdk-release).

# Ways to run this script are:
# trigger_demisto_sdk_release.sh -ct <trigger-token> -rv <release-version> [-b <branch-name> -ch <slack-channel-name>]
# For more information:
# https://confluence-dc.paloaltonetworks.com/display/DemistoContent/Demisto-sdk+automate+release+flow

if [ "$#" -lt "1" ]; then
  echo "Usage:
  $0 -ct <token>

  [-ct, --ci-token]           The ci gitlab trigger token.
  [-rv, --release-version]    The release version.
  [-r, --reviewer]            Github username of the release owner.
  [-ch, --slack-channel]      A Slack channel to send notifications to. Default is dmst-sdk-release.
  [-ib, --infra-branch]       The infra branch name to run the SDK Nightly with. Default is the current branch name.
  [-d, --is-draft]            Whether to create draft release and draft pull requests or not. Default is FALSE.
  [-s, --sdk-branch-name]     From which branch in demisto-sdk we want to create the release. Default is master.
  "
  exit 1
fi

_infra_branch="$(git branch --show-current)"
_slack_channel="dmst-sdk-release"
_is_draft="FALSE"
_sdk_branch_name="master"

# Parsing the user inputs.

while [[ "$#" -gt 0 ]]; do
  case $1 in

  -ct | --ci-token)
    _ci_token="$2"
    shift
    shift
    ;;

  -rv | --release-version)
    _release_version="$2"
    shift
    shift
    ;;

  -ib | --infra-branch)
    _infra_branch="$2"
    shift
    shift
    ;;

  -cb | --content-branch)
    _content_branch="$2"
    shift
    shift
    ;;

  -ch | --slack-channel)
    _slack_channel="$2"
    shift
    shift
    ;;

  -r | --reviewer)
    _reviewer="$2"
    shift
    shift
    ;;

  -d | --is-draft)
    _is_draft="$2"
    shift
    shift
    ;;

  -s | --sdk-branch-name)
    _sdk_branch_name="$2"
    shift
    shift
    ;;
  *)
    echo "Unknown parameter passed: $1"
    exit 1
    ;;

  esac
done

if [ -z "$_ci_token" ]; then
  echo "You must provide a ci token."
  exit 1
fi

if [ -z "$_release_version" ]; then
  echo "You must provide a release version."
  exit 1
fi

if [ -z "$_reviewer" ]; then
  echo "You must provide a github username username of the release owner."
  exit 1
fi

INFRA_PROJECT_ID=${INFRA_PROJECT_ID:-1701}
CI_SERVER_URL=${CI_SERVER_URL:-https://gitlab.xdr.pan.local} # disable-secrets-detection

export BUILD_TRIGGER_URL="${CI_SERVER_URL}/api/v4/projects/${INFRA_PROJECT_ID}/trigger/pipeline"

export URL=$(
  curl "$BUILD_TRIGGER_URL" --form "ref=${_infra_branch}" --form "token=${_ci_token}" \
    --form "variables[SDK_RELEASE]=true" \
    --form "variables[CI_TOKEN]=${_ci_token}" \
    --form "variables[REVIEWER]=${_reviewer}" \
    --form "variables[CONTENT_BRANCH_NAME]=${_content_branch}" \
    --form "variables[RELEASE_VERSION]=${_release_version}" \
    --form "variables[IS_DRAFT]=${_is_draft}" \
    --form "variables[SDK_BRANCH_NAME]=${_sdk_branch_name}" \
    --form "variables[SLACK_CHANNEL]=${_slack_channel}" | jq .web_url
)

echo "SDK release flow started:"
echo $URL
