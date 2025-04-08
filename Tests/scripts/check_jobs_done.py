import sys
from argparse import ArgumentParser
from pathlib import Path

from gitlab_slack_notifier import ARTIFACTS_FOLDER_XSIAM, ARTIFACTS_FOLDER_XSOAR, IS_CHOSEN_MACHINE_FILE_NAME, get_artifact_data

from Tests.scripts.common import (
    AUTO_UPDATE_DOCKER,
    BUCKET_UPLOAD,
    CONTENT_DOCS_NIGHTLY,
    CONTENT_DOCS_PR,
    CONTENT_MERGE,
    CONTENT_NIGHTLY,
    CONTENT_PR,
    DEPLOY_AUTO_UPGRADE_PACKS,
    DOCKERFILES_PR,
    NATIVE_NIGHTLY,
    RIT_MR,
    RIT_PUBLISH,
    RIT_RELEASE,
    SDK_NIGHTLY,
    WORKFLOW_TYPES,
)
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

DOCKERFILES_PR_JOBS = [
    "cloning-repositories",
    "build_docker_images",
    "run_pytest",
    "validate_approved_licenses_files",
    "validate_dependabot_config",
    "validate_deprecated_images",
    "scan_images",
    "test_ssl_connection",
    "parse_report",
]

AUTO_UPDATE_DOCKER_JOBS = [
    "auto-update-docker",
]

RIT_MR_JOBS = [
    "run-schema-validator",
    "run-rit-executor",
    "upload-to-internal-dev-bucket",
]

RIT_RELEASE_JOBS = [
    "verify-settings-release",
    "run-schema-validator",
    "run-rit-executor",
    "upload-to-internal-dev-bucket",
    "release-tag",
]


RIT_PUBLISH_JOBS = [
    "verify-settings-publish-version",
    "copy-to-bucket",
    "update-publish-logs",
    "sync-prod-buckets",
]

NATIVE_NIGHTLY_JOBS = [
    "cloning-repositories",
    "xsoar-saas-prepare-testing-bucket",
    "xsoar_ng_server_ga",
    "xsoar-test_playbooks_results",
]

SDK_NIGHTLY_JOBS = [
    "demisto-sdk-nightly:cloning-repositories",
    "demisto-sdk-nightly:run-pre-commit: [from-yml]",
    "demisto-sdk-nightly:run-validations",
    "demisto-sdk-nightly:test-infrastructure",
    "demisto-sdk-nightly:test-upload-flow",
    "demisto-sdk-nightly:check-idset-dependent-commands",
    "demisto-sdk-nightly:mpv2-prepare-testing-bucket",
    "demisto-sdk-nightly:xsoar-prepare-testing-bucket",
    "demisto-sdk-nightly:xpanse-prepare-testing-bucket",
    "demisto-sdk-nightly:xsoar-saas-prepare-testing-bucket",
    "demisto-sdk-nightly:platform-prepare-testing-bucket",
    "demisto-sdk-nightly:run-end-to-end-tests-general",
    "demisto-sdk-nightly:run-end-to-end-tests-xsoar",
]

BUCKET_UPLOAD_JOBS = [
    "cloning-repositories-upload-flow",
    "run-pre-commit-upload-flow: [from-yml]",
    "run-validations-upload-flow",
    "mpv2-prepare-testing-bucket-upload-flow",
    "upload-id-set-bucket",
    "xpanse-prepare-testing-bucket-upload-flow",
    "xsoar-prepare-testing-bucket-upload-flow",
    "platform-prepare-testing-bucket-upload-flow",
    "install-packs-in-server6_11",
    "install-packs-in-server6_12",
    "install-packs-in-server-master",
    "install-packs-in-xsiam-ga",
    "install-packs-in-xsoar-ng-ga",
    "upload-packs-to-marketplace",
    "upload-packs-to-marketplace-v2",
    "upload-packs-to-xpanse-marketplace",
    "upload-packs-to-platform-marketplace",
    "upload-content-graph-data-to-bigquery",
]

CONTENT_COMMON_JOBS = [
    "cloning-repositories",
    "run-pre-commit: [from-yml]",
    "run-validations",
    "mpv2-prepare-testing-bucket",
    "xpanse-prepare-testing-bucket",
    "xsoar-prepare-testing-bucket",
    "xsoar-saas-prepare-testing-bucket",
    "platform-prepare-testing-bucket",
    "xsiam_server_ga",
    "xsoar_ng_server_ga",
    "tests_xsoar_server: [Server 6.11]",
    "tests_xsoar_server: [Server 6.12]",
    "tests_xsoar_server: [Server Master]",
    "xsoar-test_playbooks_results",
    "xsiam-test_playbooks_results",
    "xsiam-test_modeling_rule_results",
]

CONTENT_PR_JOBS = CONTENT_COMMON_JOBS + [
    "validate-content-conf",
    "test-upload-flow",
    "stop-running-pipelines",
]

CONTENT_MERGE_JOBS = CONTENT_COMMON_JOBS + [
    "merge-dev-secrets",
    "xsoar_ng_server_ga",
]
DEPLOY_AUTO_UPGRADE_PACKS_JOBS = [
    "deploy-auto-upgrade-check-user-permissions",
    "deploy-groups-file: [xsoar]",
    "deploy-groups-file: [marketplacev2]",
    "deploy-groups-file: [xpanse]",
    "deploy-groups-file: [xsoar_saas]",
    "deploy-auto-upgrade-sync-buckets-between-projects",
]
CONTENT_NIGHTLY_JOBS = CONTENT_COMMON_JOBS


CONTENT_DOCS_JOBS_BASE = [
    "build-docs",
]

CONTENT_DOCS_PR_JOBS = CONTENT_DOCS_JOBS_BASE
CONTENT_DOCS_NIGHTLY_JOBS = CONTENT_DOCS_JOBS_BASE

JOBS_PER_TRIGGERING_WORKFLOW = {
    DOCKERFILES_PR: DOCKERFILES_PR_JOBS,
    AUTO_UPDATE_DOCKER: AUTO_UPDATE_DOCKER_JOBS,
    CONTENT_NIGHTLY: CONTENT_NIGHTLY_JOBS,
    SDK_NIGHTLY: SDK_NIGHTLY_JOBS,
    NATIVE_NIGHTLY: NATIVE_NIGHTLY_JOBS,
    BUCKET_UPLOAD: BUCKET_UPLOAD_JOBS,
    CONTENT_DOCS_PR: CONTENT_DOCS_PR_JOBS,
    CONTENT_DOCS_NIGHTLY: CONTENT_DOCS_NIGHTLY_JOBS,
    CONTENT_PR: CONTENT_PR_JOBS,
    CONTENT_MERGE: CONTENT_MERGE_JOBS,
    DEPLOY_AUTO_UPGRADE_PACKS: DEPLOY_AUTO_UPGRADE_PACKS_JOBS,
    RIT_MR: RIT_MR_JOBS,
    RIT_RELEASE: RIT_RELEASE_JOBS,
    RIT_PUBLISH: RIT_PUBLISH_JOBS,
}


def parse_args():
    parser = ArgumentParser()
    parser.add_argument("--job-done-files", required=True, help="the folder where the job files are located")
    parser.add_argument(
        "-tw",
        "--triggering-workflow",
        help="The type of ci pipeline workflow the notifier is reporting on",
        choices=WORKFLOW_TYPES,
    )
    return parser.parse_args()


def main():
    install_logging("check_jobs_done.log", logger=logging)
    args = parse_args()

    base_path = Path(args.job_done_files)
    should_fail = False
    for job in JOBS_PER_TRIGGERING_WORKFLOW[args.triggering_workflow]:
        if "run-validations" in job:
            continue
        job_file = base_path / f"{job}.txt"
        logging.info(f"checking job {job} with file {job_file} in {job_file.absolute()}")
        if not job_file.exists():
            logging.error(f"job {job} is not done yet")
            should_fail = True
        elif job_file.read_text().strip() != "done":
            logging.error(f"something isn't OK with job name {job}")
            should_fail = True

    if args.triggering_workflow == CONTENT_PR:
        if get_artifact_data(ARTIFACTS_FOLDER_XSOAR, IS_CHOSEN_MACHINE_FILE_NAME) or get_artifact_data(
            ARTIFACTS_FOLDER_XSIAM, IS_CHOSEN_MACHINE_FILE_NAME
        ):
            logging.error("The machine has been chosen by a customer label.")
            should_fail = True

    if should_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
