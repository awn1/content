import sys
from argparse import ArgumentParser
from pathlib import Path

from Tests.scripts.common import (
    BUCKET_UPLOAD,
    CONTENT_DOCS_NIGHTLY,
    CONTENT_DOCS_PR,
    CONTENT_MERGE,
    CONTENT_NIGHTLY,
    CONTENT_PR,
    DOCKERFILES_PR,
    NATIVE_NIGHTLY,
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
    "demisto-sdk-nightly:run-validations-new-validate-flow",
    "demisto-sdk-nightly:test-infrastructure",
    "demisto-sdk-nightly:test-upload-flow",
    "demisto-sdk-nightly:check-idset-dependent-commands",
    "demisto-sdk-nightly:mpv2-prepare-testing-bucket",
    "demisto-sdk-nightly:xsoar-prepare-testing-bucket",
    "demisto-sdk-nightly:xpanse-prepare-testing-bucket",
    "demisto-sdk-nightly:xsoar-saas-prepare-testing-bucket",
    "demisto-sdk-nightly:run-end-to-end-tests-general",
    "demisto-sdk-nightly:run-end-to-end-tests-xsoar",
]

BUCKET_UPLOAD_JOBS = [
    "cloning-repositories-upload-flow",
    "run-pre-commit-upload-flow: [from-yml]",
    "run-validations-upload-flow",
    "run-validations-upload-flow-new-validate-flow",
    "mpv2-prepare-testing-bucket-upload-flow",
    "upload-id-set-bucket",
    "xpanse-prepare-testing-bucket-upload-flow",
    "xsoar-prepare-testing-bucket-upload-flow",
    "install-packs-in-server6_11",
    "install-packs-in-server6_12",
    "install-packs-in-server-master",
    "install-packs-in-xsiam-ga",
    "install-packs-in-xsoar-ng-ga",
    "upload-packs-to-marketplace",
    "upload-packs-to-marketplace-v2",
    "upload-packs-to-xpanse-marketplace",
]

CONTENT_COMMON_JOBS = [
    "cloning-repositories",
    "run-pre-commit: [from-yml]",
    "run-validations",
    "run-validations-new-validate-flow",
    "mpv2-prepare-testing-bucket",
    "xpanse-prepare-testing-bucket",
    "xsoar-prepare-testing-bucket",
    "xsoar-saas-prepare-testing-bucket",
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

CONTENT_NIGHTLY_JOBS = CONTENT_COMMON_JOBS


CONTENT_DOCS_JOBS_BASE = [
    "build-docs",
]

CONTENT_DOCS_PR_JOBS = CONTENT_DOCS_JOBS_BASE
CONTENT_DOCS_NIGHTLY_JOBS = CONTENT_DOCS_JOBS_BASE

JOBS_PER_TRIGGERING_WORKFLOW = {
    DOCKERFILES_PR: DOCKERFILES_PR_JOBS,
    CONTENT_NIGHTLY: CONTENT_NIGHTLY_JOBS,
    SDK_NIGHTLY: SDK_NIGHTLY_JOBS,
    NATIVE_NIGHTLY: NATIVE_NIGHTLY_JOBS,
    BUCKET_UPLOAD: BUCKET_UPLOAD_JOBS,
    CONTENT_DOCS_PR: CONTENT_DOCS_PR_JOBS,
    CONTENT_DOCS_NIGHTLY: CONTENT_DOCS_NIGHTLY_JOBS,
    CONTENT_PR: CONTENT_PR_JOBS,
    CONTENT_MERGE: CONTENT_MERGE_JOBS,
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
        if "new-validate-flow" in job:
            continue
        job_file = base_path / f"{job}.txt"
        logging.info(f"checking job {job} with file {job_file} in {job_file.absolute()}")
        if not job_file.exists():
            logging.error(f"job {job} is not done yet")
            should_fail = True
        elif job_file.read_text().strip() != "done":
            logging.error(f"something isn't OK with job name {job}")
            should_fail = True

    if should_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
