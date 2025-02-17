import logging

import json5
from google.api_core.exceptions import NotFound, PermissionDenied

from SecretActions.google_secret_manager_handler import GoogleSecreteManagerModule, SecretLabels
from Tests.scripts.infra.models import PublicApiKey
from Tests.scripts.infra.resources.constants import AUTOMATION_GCP_PROJECT, GSM_SERVICE_ACCOUNT

BUILD_MACHINE_GSM_API_KEY = "api-key"
BUILD_MACHINE_GSM_AUTH_ID = "x-xdr-auth-id"
BUILD_MACHINE_GSM_TOKEN = "token"


def get_existing_secret(gsm_object: GoogleSecreteManagerModule, server_id: str) -> tuple[dict, str]:
    # Checks if the secret exists
    logging.info(f"Getting existing secret of {server_id}")
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


def add_build_machine_secret_to_gsm(
    server_id: str,
    machine_type: str,
    project_id: str = AUTOMATION_GCP_PROJECT,
    gsm_object: GoogleSecreteManagerModule = None,
    token_value: str | None = None,
    public_api_key: PublicApiKey = None,
) -> tuple[dict, str]:
    if not gsm_object:
        gsm_object: GoogleSecreteManagerModule = GoogleSecreteManagerModule(
            project_id=project_id,
            service_account_file=GSM_SERVICE_ACCOUNT,  # used from build
        )

    server_value = {}
    if token_value:
        server_value.update({BUILD_MACHINE_GSM_TOKEN: token_value})

    if public_api_key:
        server_value.update({BUILD_MACHINE_GSM_API_KEY: public_api_key.key, BUILD_MACHINE_GSM_AUTH_ID: public_api_key.id})

    existing_value, secret_version = get_existing_secret(gsm_object, server_id)
    updated_value: dict = existing_value | server_value
    if updated_value != existing_value:
        secret_version = gsm_object.add_secret_version(
            server_id, json5.dumps(updated_value, quote_keys=True, indent=4, sort_keys=True)
        )
        # Update the labels for the secret
        gsm_object.update_secret(server_id, {SecretLabels.MACHINE.value: gsm_object.convert_to_gsm_format(machine_type)})
    else:
        logging.info(f"Skipping update for {server_id}, its values did not change")

    return updated_value, secret_version
