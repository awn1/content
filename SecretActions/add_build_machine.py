import argparse
import logging
import os

import coloredlogs
import json5
from google.api_core.exceptions import NotFound, PermissionDenied
from google.auth.exceptions import DefaultCredentialsError

from SecretActions.add_gsm_secret import YELLOW_BOLD_PRINT
from SecretActions.google_secret_manager_handler import DEV_PROJECT_ID, GoogleSecreteManagerModule, SecretLabels
from Tests.scripts.infra.models import PublicApiKey
from Tests.scripts.infra.resources.constants import AUTOMATION_GCP_PROJECT, COMMENT_FIELD_NAME, GSM_SERVICE_ACCOUNT
from Tests.scripts.infra.xsoar_api import SERVER_TYPE_TO_CLIENT_TYPE

BUILD_MACHINE_GSM_API_KEY = "api-key"
BUILD_MACHINE_GSM_AUTH_ID = "x-xdr-auth-id"
BUILD_MACHINE_GSM_TOKEN = "token"

BUILD_MACHINE_INPUT_SERVERS_FILE = "servers-json"

INPUT_TYPES = [BUILD_MACHINE_GSM_API_KEY, BUILD_MACHINE_GSM_TOKEN, BUILD_MACHINE_INPUT_SERVERS_FILE]
MACHINE_TYPES = list(SERVER_TYPE_TO_CLIENT_TYPE.keys())

SECRET_VALUES = [BUILD_MACHINE_GSM_API_KEY, BUILD_MACHINE_GSM_TOKEN, BUILD_MACHINE_GSM_AUTH_ID]


def validate_input(options: argparse.Namespace, attr_validation: tuple) -> json5:
    # Validate file exists and is in json5 format
    logging.debug("validating secret")
    try:
        with open(options.input, encoding="utf-8") as json_file:
            json_object = json5.load(json_file)
    except FileNotFoundError:
        raise Exception(f"Could not find the file at: {options.input}")
    except ValueError as e:
        raise Exception(f"Could not convert file to json5, got the following error: {e!s}")

    # Validate mandatory properties in the secret
    if options.input_type == BUILD_MACHINE_INPUT_SERVERS_FILE:
        missing_attrs = any(
            any(attr for attr in attr_validation if attr not in server_value)
            for server_id, server_value in json_object.items()
            if server_id != COMMENT_FIELD_NAME
        )
        if missing_attrs:
            raise Exception(f"Missing mandatory properties, one of this options: {','.join(attr_validation)}")

    return json_object


def create_new_values(server_value: dict | str, input_type: str) -> dict[str, str]:
    if input_type == BUILD_MACHINE_INPUT_SERVERS_FILE:
        return {key: value for key, value in server_value.items() if key in SECRET_VALUES}
    if input_type == BUILD_MACHINE_GSM_API_KEY:
        return {BUILD_MACHINE_GSM_API_KEY: server_value}
    if input_type == BUILD_MACHINE_GSM_TOKEN:
        return {BUILD_MACHINE_GSM_TOKEN: server_value}


def get_existing_secret(gsm_object: GoogleSecreteManagerModule, server_id: str) -> tuple[dict, str]:
    # Checks if the secret exists
    try:
        return gsm_object.get_secret(server_id, with_version=True)
    # Secret was not found, creates new secret
    except NotFound:
        gsm_object.create_secret(server_id)
        return {}, "1"
    except PermissionDenied as e:
        if "secretmanager.versions.access" in str(e):
            raise PermissionDenied(
                "Permission 'secretmanager.versions.access' denied, ask for oproxy-developer permissions "
                "role in #xdr-permissions-dev channel."
            ) from e
        raise


def add_build_machine_secrets_from_file(secret_json: json5, input_type: str, project_id: str, machine_type: str):
    """Adding the build machine secret from file to GSM"""
    logging.debug("Adding the build machine secret from file to GSM")
    gsm_object: GoogleSecreteManagerModule = GoogleSecreteManagerModule(project_id=project_id)

    for server_id, server_value in secret_json.items():
        if server_id == COMMENT_FIELD_NAME:
            logging.debug("Skipping comment")
            continue
        add_build_machine_secret_to_gsm(server_id, machine_type, input_type, project_id, gsm_object, server_value)

    print(
        YELLOW_BOLD_PRINT + "The secrets were successfully added to GSM. "
        "Make sure to add other relevant configurations to the servers json file." + YELLOW_BOLD_PRINT
    )


def add_build_machine_secret_to_gsm(
    server_id: str,
    machine_type: str,
    input_type: str = None,
    project_id: str = AUTOMATION_GCP_PROJECT,
    gsm_object: GoogleSecreteManagerModule = None,
    server_value: dict | str = None,
    public_api_key: PublicApiKey = None,
) -> tuple[dict, str]:
    if not gsm_object:
        gsm_object: GoogleSecreteManagerModule = GoogleSecreteManagerModule(
            project_id=project_id,
            service_account_file=GSM_SERVICE_ACCOUNT,  # used from build
        )
    if server_value:
        server_value: dict = create_new_values(server_value, input_type)
    else:
        server_value = {BUILD_MACHINE_GSM_API_KEY: public_api_key.key, BUILD_MACHINE_GSM_AUTH_ID: public_api_key.id}

    existing_value, secret_version = get_existing_secret(gsm_object, server_id)
    updated_value: dict = existing_value | server_value
    if updated_value != existing_value:
        secret_version = gsm_object.add_secret_version(
            server_id, json5.dumps(updated_value, quote_keys=True, indent=4, sort_keys=True)
        )
        # Update the labels for the secret
        gsm_object.update_secret(server_id, {SecretLabels.MACHINE.value: gsm_object.convert_to_gsm_format(machine_type)})
    else:
        logging.debug(f"Skipping update for {server_id}, its values did not change")
    return updated_value, secret_version


def run(options: argparse.Namespace):
    try:
        project_id: str = options.gsm_project_id if options.gsm_project_id else DEV_PROJECT_ID
        os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
        secret_json: json5 = validate_input(options, attr_validation=(BUILD_MACHINE_GSM_AUTH_ID,))
        add_build_machine_secrets_from_file(secret_json, options.input_type, project_id, options.machine_type)

    except DefaultCredentialsError:
        logging.error("Insufficient permissions for gcloud. Run `gcloud auth application-default login`.")
    except Exception as e:
        logging.error(e)


def options_handler(args=None):
    parser = argparse.ArgumentParser(
        description="Utility to insert build machine secrets to Google Secret Manager. "
        "Docs: https://confluence-dc.paloaltonetworks.com/display/DemistoContent/Google+Secret+Manager+-+Add+Build+Machine"
    )
    parser.add_argument("-gpid", "--gsm_project_id", help="The project id in GCP.", required=False)

    parser.add_argument(
        "-i",
        "--input",
        help="The secret json file path with a dict of several build machines we want to add.",
        required=True,
    )
    parser.add_argument(
        "-t",
        "--input-type",
        choices=INPUT_TYPES,
        default=BUILD_MACHINE_GSM_API_KEY,
        help="The type of values in the secret json file provided.",
        required=True,
    )
    parser.add_argument(
        "-m",
        "--machine-type",
        choices=MACHINE_TYPES,
        help="The machine type of the values in the secret json file provided.",
        required=True,
    )
    options = parser.parse_args(args)

    return options


if __name__ == "__main__":
    coloredlogs.install(level="DEBUG", fmt="[%(levelname)s] - %(message)s")
    options = options_handler()
    run(options)
