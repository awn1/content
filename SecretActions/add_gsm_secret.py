import argparse
import os
import coloredlogs
import io
import logging

import json5
from google.api_core.exceptions import NotFound, PermissionDenied, InvalidArgument
from google.auth.exceptions import DefaultCredentialsError
from SecretActions.google_secret_manager_handler import GoogleSecreteManagerModule, DEV_PROJECT_ID  # not added to build


def validate_secret(secret: str, options: argparse.Namespace, project_id, attr_validation: tuple) -> json5:
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
        with io.open(secret, "r", encoding="utf-8") as json_file:
            json_object = json5.load(json_file)
    except FileNotFoundError:
        raise Exception(f'Could not find the file at: {secret}')
    except ValueError as e:
        raise Exception(f'Could not convert to json5, we got the following error: {str(e)}')

    # Validate mandatory properties in the secret
    missing_attrs = [attr for attr in attr_validation if attr not in json_object]
    if missing_attrs:
        raise Exception(f"Missing mandatory properties: {','.join(missing_attrs)}")

    # Validate necessary properties to create a dev secret
    if options.branch:
        if '/' in options.branch:
            raise Exception('The branch name must not have "/" in it, because it will be considered as part of the secret path.')
        if not options.branch.islower():
            options.branch = GoogleSecreteManagerModule.convert_to_gsm_format(options.branch)
            logging.debug(f'The branch name had uppercase letters in it, converting to lowercase: {options.branch}.')
        if project_id != DEV_PROJECT_ID:
            raise Exception(f'Branch name is not supported for a prod secret, you provided {project_id=}.')
    elif project_id == DEV_PROJECT_ID:
        raise Exception('Missing branch name for a dev secret.')

    return json_object


def upsert_secret(gsm_object: GoogleSecreteManagerModule, options: argparse.Namespace, gsm_project_id: str,
                  secret_json: json5) -> None:
    """
    Adds/updates th secret
    :param gsm_object: The GSM object
    :param options: The passed script variables
    :param gsm_project_id: The GCP project ID
    :param secret_json: The secret to add/update
    """

    instance = f'__{secret_json.get("instance_name")}' if secret_json.get('instance_name') else ''
    full_secret_name = gsm_object.convert_to_gsm_format(f'{secret_json.get("name", )}{instance}', secret_name=True)
    labels = {'secret_id': gsm_object.convert_to_gsm_format(full_secret_name)}
    if gsm_project_id == DEV_PROJECT_ID:
        full_secret_name = f'{options.branch}__{full_secret_name}'
        labels['dev'] = 'true'
        labels['branch'] = options.branch
    # Checks if the secret exist
    try:
        gsm_object.get_secret(gsm_project_id, full_secret_name)
    # Secret was not found, creates new secret
    except NotFound:
        gsm_object.create_secret(gsm_project_id, full_secret_name, labels)
    except PermissionDenied as e:
        if "secretmanager.versions.access" in str(e):
            raise PermissionDenied("Permission 'secretmanager.versions.access' denied, ask for oproxy-developer permissions "
                                   "role in #xdr-permissions-dev channel.") from e
        raise
    # Adds a version for the created/updated secret
    gsm_object.add_secret_version(gsm_project_id, full_secret_name, json5.dumps(secret_json, quote_keys=True))
    # Update the labels for the secret
    gsm_object.update_secret(gsm_project_id, full_secret_name, labels)


def run(options: argparse.Namespace):
    try:
        project_id = options.gsm_project_id if options.gsm_project_id else DEV_PROJECT_ID
        secret_json = validate_secret(options.input, options, project_id, attr_validation=('name', 'params'))
        os.environ['GOOGLE_CLOUD_PROJECT'] = project_id
        gsm_object = GoogleSecreteManagerModule(project_id=project_id)
        upsert_secret(gsm_object, options, project_id, secret_json)
    except DefaultCredentialsError:
        logging.error("Insufficient permissions for gcloud. Run `gcloud auth application-default login`.")
    except InvalidArgument as e:
        branch_msg = "Branch name is invalid.\n" if "labels.branch" in e else ""
        logging.error(f"{branch_msg}{e}")
    except Exception as e:
        logging.error(e)


def options_handler(args=None):
    parser = argparse.ArgumentParser(
        description='Utility for upsert secrets to Google Secret Manager. '
                    'Docs: https://confluence-dc.paloaltonetworks.com/display/DemistoContent/Google+Secret+Manager+-+User+Guide')
    parser.add_argument('-gpid', '--gsm_project_id', help='The project id in GCP.', required=False)
    parser.add_argument('-i', '--input', help='The secret json file path with the secret value we want to add.')
    parser.add_argument('-b', '--branch',
                        help='The branch name to add the secret for, required when adding a dev secret.',
                        required=False)
    options = parser.parse_args(args)

    return options


if __name__ == '__main__':
    coloredlogs.install(level='DEBUG', fmt="[%(levelname)s] - %(message)s")
    options = options_handler()
    run(options)
