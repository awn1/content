import argparse
import logging
import os

import coloredlogs
import json5
from google.api_core.exceptions import InvalidArgument, NotFound, PermissionDenied
from google.auth.exceptions import DefaultCredentialsError

from SecretActions.google_secret_manager_handler import (
    DEV_PROJECT_ID,
    SYNC_GSM_LABEL,
    ExpirationData,
    GoogleSecreteManagerModule,
    SecretLabels,
    create_github_client,
)
from Tests.scripts.github_client import GithubClient, GithubPullRequest

EXPIRATION_LABELS = [
    ExpirationData.CREDS_EXPIRATION_LABEL_NAME,
    ExpirationData.LICENSE_EXPIRATION_LABEL_NAME,
    ExpirationData.JIRA_LINK_LABEL_NAME,
    ExpirationData.CENTRIFY_LABEL_NAME,
    ExpirationData.SKIP_REASON_LABEL_NAME,
    ExpirationData.SECRET_OWNER,
]

DEFAULT_PR_COMMENT = (
    f'The "{SYNC_GSM_LABEL}" label has been added to your PR.'
    "\nIf you decide not to merge the new instance you added, make sure to remove this label before closing the PR."
)
YELLOW_BOLD_PRINT = "\033[1;33m"


def validate_secret(
    secret: str, options: argparse.Namespace, project_id, attr_validation: tuple, github_client: GithubClient | None = None
) -> json5:
    """
    Validate that the secret comply to our format
    :param secret: The secret json as a string
    :param options: The passed script variables
    :param project_id: The passed project id to insert the secret to
    :param attr_validation: A list of properties we expect the secret to have
    :return: The validated secret as a json 5
    """
    # Validate file exist and json 5 format
    try:
        with open(secret, encoding="utf-8") as json_file:
            json_object = json5.load(json_file)
    except FileNotFoundError:
        raise Exception(f"Could not find the file at: {secret}")
    except ValueError as e:
        raise Exception(f"Could not convert to json5, got the following error: {e!s}")

    # Validate mandatory properties in the secret
    missing_attrs = [attr for attr in attr_validation if attr not in json_object]
    if missing_attrs:
        raise Exception(f"Missing mandatory properties: {','.join(missing_attrs)}")

    # validate expiration fields' format
    if cred_expiration := json_object.get(ExpirationData.CREDS_EXPIRATION_LABEL_NAME):
        res = GoogleSecreteManagerModule.GoogleSecretTools.calculate_expiration_date(cred_expiration)
        if not res:
            raise Exception("invalid expiration date.")
        json_object[ExpirationData.CREDS_EXPIRATION_LABEL_NAME] = res

    if license_expiration := json_object.get(ExpirationData.LICENSE_EXPIRATION_LABEL_NAME):
        res = GoogleSecreteManagerModule.GoogleSecretTools.calculate_expiration_date(license_expiration)
        if not res:
            raise Exception("invalid expiration date.")
        json_object[ExpirationData.CREDS_EXPIRATION_LABEL_NAME] = res

    # Validate necessary properties to create a dev secret
    if options.pr_number:
        if project_id != DEV_PROJECT_ID:
            raise Exception(f"Pull Request number is not supported for a prod secret, you provided {project_id=}.")
        try:
            if github_client:
                github_client.get_pr_from_pr_number(options.pr_number)
        except Exception as e:
            raise Exception(
                f"Pull Request was not found for {options.pr_number} - " f"{e!s} . Make sure the PR number you provided is valid."
            )

    elif project_id == DEV_PROJECT_ID:
        raise Exception("Missing Pull Request number for a dev secret.")

    return json_object


def _prepare_additional_labels(
    gsm_object: GoogleSecreteManagerModule, options: argparse.Namespace, labels_to_add: list[str] = EXPIRATION_LABELS
) -> dict:
    """Creates a list with all labels to be added according to labels_to_add.

    Args:
        options (argparse.Namespace): _description_
        labels_to_add (list[str], optional): _description_. Defaults to EXPIRATION_LABELS.

    Returns:
        dict: The labels to add with the required value
    """
    additional_labels = dict()
    options_labels = options.__dict__

    # Validate pack_id is present
    if not options.pack_id:
        raise ValueError(
            "The pack_id label is required for all secrets. "
            "The value should be the pack folder name of the integration which the secret is used for. "
            "Please provide a pack_id by using the -pi flag i.e., -pi 'Slack'."
        )
    additional_labels["pack_id"] = gsm_object.convert_to_gsm_format(options.pack_id)  # Add the pack_id label

    for label in labels_to_add:
        if label_value := options_labels.get(label):
            if label in (ExpirationData.CREDS_EXPIRATION_LABEL_NAME, ExpirationData.LICENSE_EXPIRATION_LABEL_NAME):
                label_value = GoogleSecreteManagerModule.GoogleSecretTools.calculate_expiration_date(label_value)
            additional_labels[label] = label_value

    return additional_labels


def upsert_secret(
    gsm_object: GoogleSecreteManagerModule, options: argparse.Namespace, gsm_project_id: str, secret_json: json5
) -> None:
    """
    Adds/updates the secret.
    :param gsm_object: The GSM object
    :param options: The passed script variables
    :param gsm_project_id: The GCP project ID
    :param secret_json: The secret to add/update
    """

    instance = f'__{secret_json.get("instance_name")}' if secret_json.get("instance_name") else ""
    full_secret_name = gsm_object.convert_to_gsm_format(f'{secret_json.get("name", )}{instance}', secret_name=True)

    # Building the labels to add
    labels = _prepare_additional_labels(gsm_object, options)

    if gsm_project_id == DEV_PROJECT_ID:
        full_secret_name = f"{options.pr_number}__{full_secret_name}"
        labels.update({SecretLabels.DEV_SECRET.value: "true", SecretLabels.PR_NUMBER.value: options.pr_number})
    # Checks if the secret exist
    try:
        gsm_object.get_secret(full_secret_name)
    # Secret was not found, creates new secret
    except NotFound:
        gsm_object.create_secret(full_secret_name, labels=labels)
    except PermissionDenied as e:
        if "secretmanager.versions.access" in str(e):
            raise PermissionDenied(
                "Permission 'secretmanager.versions.access' denied, ask for oproxy-developer permissions "
                "role in #xdr-permissions-dev channel."
            ) from e
        raise
    # Adds a version for the created/updated secret
    gsm_object.add_secret_version(full_secret_name, json5.dumps(secret_json, quote_keys=True))
    # Update the labels for the secret
    gsm_object.update_secret(full_secret_name, labels)


def update_pr(github_client: GithubClient, options: argparse.Namespace):
    pull_request = GithubPullRequest(github_client.github_token, fail_on_error=True, pr_number=options.pr_number)
    pull_request.add_labels_to_pr([SYNC_GSM_LABEL])
    logging.info(f"The PR {options.pr_number} was updated with the '{SYNC_GSM_LABEL}' label.")


def add_secret_to_dev(options: argparse.Namespace, project_id: str):
    """Adding the secret to dev project"""
    gsm_object = GoogleSecreteManagerModule(project_id=project_id)
    github_client = create_github_client(gsm_object, DEV_PROJECT_ID)

    secret_json = validate_secret(
        options.input, options, project_id, attr_validation=("name", "params"), github_client=github_client
    )
    upsert_secret(gsm_object, options, project_id, secret_json)

    update_pr(github_client, options)

    print(
        YELLOW_BOLD_PRINT
        + f"The secret was successfully added to GSM, and the '{SYNC_GSM_LABEL}' label has been \
            \nadded to your PR. If you decide to not merge the new secret you added, make sure to remove \
            \nthis label before closing the PR."
        + YELLOW_BOLD_PRINT
    )


def add_secret_to_prod(options: argparse.Namespace, project_id: str):
    """Adding the secret to prod project"""
    gsm_object = GoogleSecreteManagerModule(project_id=project_id)
    secret_json = validate_secret(options.input, options, project_id, attr_validation=("name", "params"))
    upsert_secret(gsm_object, options, project_id, secret_json)

    print(YELLOW_BOLD_PRINT + "The secret was successfully added to prod GSM." + YELLOW_BOLD_PRINT)


def run(options: argparse.Namespace):
    try:
        project_id = options.gsm_project_id if options.gsm_project_id else DEV_PROJECT_ID
        os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
        if project_id == DEV_PROJECT_ID:
            add_secret_to_dev(options, project_id)
        else:
            add_secret_to_prod(options, project_id)

    except DefaultCredentialsError:
        logging.error("Insufficient permissions for gcloud. Run `gcloud auth application-default login`.")
    except InvalidArgument as e:
        pr_msg = "PR number is invalid.\n" if "labels.pr_number" in e else ""
        logging.error(f"{pr_msg}{e}")
    except Exception as e:
        logging.error(e)


def options_handler(args=None):
    parser = argparse.ArgumentParser(
        description="Utility for upsert secrets to Google Secret Manager. "
        "Docs: https://confluence-dc.paloaltonetworks.com/display/DemistoContent/Google+Secret+Manager+-+User+Guide"
    )
    parser.add_argument("-gpid", "--gsm_project_id", help="The project id in GCP.", required=False)
    parser.add_argument("-i", "--input", help="The secret json file path with the secret value we want to add.")
    parser.add_argument(
        "-pr", "--pr_number", help="The pr number to add the secret for, required when adding a dev secret.", required=False
    )
    parser.add_argument(
        "-ce",
        "--credential_expiration",
        help="The expiration time of the instance's credentials in the secret, matching format: yyyy-mm-dd.",
    )
    parser.add_argument(
        "-le", "--license_expiration", help="The expiration time of the product's license, matching format: yyyy-mm-dd."
    )
    parser.add_argument(
        "--owner",
        choices=["tpm", "partner", "lab"],
        default="lab",
        help="The secret owner, responsible for any issues or changes.",
    )
    parser.add_argument("-cl", "--centrify", required=False, help="The secret link in Centrify Vault.")
    parser.add_argument("-pi", "--pack_id", required=True, help="The pack folder name of this secret's integration.")
    parser.add_argument("--jira_link", required=False, help="The link of the secret updating request.")
    parser.add_argument("--skip_reason", required=False, help="A skipping reason to add.")
    options = parser.parse_args(args)

    return options


if __name__ == "__main__":
    coloredlogs.install(level="DEBUG", fmt="[%(levelname)s] - %(message)s")
    options = options_handler()
    run(options)
