#!/usr/bin/env bash
set -ex

echo "CI_COMMIT_BRANCH: $CI_COMMIT_BRANCH CI: $CI DEMISTO_README_VALIDATION: $DEMISTO_README_VALIDATION, CI_COMMIT_SHA: $CI_COMMIT_SHA, LAST_UPLOAD_COMMIT: $LAST_UPLOAD_COMMIT"
if [[ $CI_COMMIT_BRANCH = master ]] || [[ "${IS_NIGHTLY}" == "true" ]] || [[ "${BUCKET_UPLOAD}" == "true" ]] || [[ "${DEMISTO_SDK_NIGHTLY}" == "true" ]] || [[ "${SHOULD_VALIDATE_ALL}" == "true" ]]; then
  if [[ -n "${PACKS_TO_UPLOAD}" ]]; then
    echo "Packs upload - Validating only the supplied packs"
    PACKS_TO_UPLOAD_SPACED=${PACKS_TO_UPLOAD//,/ }
    for item in $PACKS_TO_UPLOAD_SPACED; do
      python3 -m demisto_sdk validate -i Packs/"$item" --post-commit --config-path validation_config.toml
    done
  else
    if [[ "${IS_NIGHTLY}" == "true" && "${CI_COMMIT_BRANCH}" == "master" ]]; then
      PREV_VER=$LAST_UPLOAD_COMMIT
    else
      PREV_VER="origin/master"
    fi
    python3 -m demisto_sdk validate -a --prev-ver $PREV_VER --config-path validation_config.toml
  fi
elif [ -n "${CONTRIB_BRANCH}" ]; then
  python3 -m demisto_sdk validate -g --config-path validation_config.toml
else
  python3 -m demisto_sdk validate -g --post-commit --config-path validation_config.toml
fi
