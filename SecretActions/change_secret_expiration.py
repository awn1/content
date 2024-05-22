import argparse
import logging
import dateparser
from datetime import datetime
from google.auth.exceptions import DefaultCredentialsError

from SecretActions.google_secret_manager_handler import GoogleSecreteManagerModule, ExpirationData  # noqa: E402

DEV_PROJECT_ID = '269994096945'
DATE_FORMAT = '%Y-%m-%d'


class GoogleSecreteExpirationManagerModule(GoogleSecreteManagerModule):

    def update_secret_metadata(self, project_id: str, secret_id: str, labels: dict = None, deprecate: bool = False) -> None:
        """
        Update a secret in GSM
        :param project_id: The project ID for GCP
        :param secret_id: The name of the secret in GSM
        :param labels: A dict with the labels we want to add to the secret

        """
        name = self.client.secret_path(project_id, secret_id)

        metadata = self.client.get_secret(request={"name": name})
        current_labels = metadata.labels if metadata.labels else {}

        new_labels = dict(current_labels) | labels
        if deprecate:
            logging.debug("removing expiration due to deprecation request.")
            new_labels.pop(ExpirationData.CREDS_EXPIRATION_LABEL_NAME, None)
            new_labels.pop(ExpirationData.LICENSE_EXPIRATION_LABEL_NAME, None)

        secret = {"name": name, "labels": new_labels}
        update_mask = {"paths": ["labels"]}
        self.client.update_secret(
            request={"secret": secret, "update_mask": update_mask}
        )
        logging.debug("Successfully updated secret's metadata")


def calculate_expiration_date(expiration_date: str) -> str:
    """Calculating expiration date based on input.

    Args:
        expiration_date (str): a date representing string, such "in 1 day", "3 days", "2024-05-01", etc

    Returns:
        str: a standardized string for the date requested.
    """
    logging.debug(f"Parsing expiration date from: {expiration_date}")
    d = dateparser.parse(expiration_date)
    logging.debug("Parsed successfully.")

    return datetime.strftime(d, DATE_FORMAT)

def get_labels_to_update(args: argparse.Namespace) -> list[dict]:
    if args.deactivate:
            labels_to_add = {ExpirationData.Status.STATUS_LABEL_NAME: ExpirationData.Status.INACTIVE_STATUS,
                             ExpirationData.CREDS_EXPIRATION_LABEL_NAME: None,
                             ExpirationData.LICENSE_EXPIRATION_LABEL_NAME: None}
    else:
        labels_to_add = {ExpirationData.Status.STATUS_LABEL_NAME: ExpirationData.Status.ACTIVE_STATUS}
        if args.credential_expiration:
            cred_exp_date = calculate_expiration_date(args.credential_expiration)
            labels_to_add[ExpirationData.CREDS_EXPIRATION_LABEL_NAME] = cred_exp_date
        if args.license_expiration:
            license_exp_date = calculate_expiration_date(args.license_expiration)
            labels_to_add[ExpirationData.LICENSE_EXPIRATION_LABEL_NAME] = license_exp_date
        if not args.license_expiration and not args.credential_expiration:
            raise ValueError("Please provide license or credential expiration date.")

    if args.centrify:
            labels_to_add[ExpirationData.CENTRIFY_LABEL_NAME] = args.centrify
    if args.skip_reason:
        labels_to_add[ExpirationData.SKIP_REASON_LABEL_NAME] = args.skip_reason
    if args.jira_link:
        labels_to_add[ExpirationData.JIRA_LINK_LABEL_NAME] = args.jira_link

    logging.debug("successfully created label's data.")

    return labels_to_add


def run(options: argparse.Namespace):
    try:
        gsm_object = GoogleSecreteExpirationManagerModule()
        project_id = options.gsm_project_id if options.gsm_project_id else DEV_PROJECT_ID
        logging.debug(f"running on {project_id=}")

        logging.debug("Getting labels to update from inputs.")
        labels_to_add = get_labels_to_update(options)

        logging.debug(f"Updating secret {options.secret_name}")
        gsm_object.update_secret_metadata(
            project_id, options.secret_name, labels=labels_to_add)

    except DefaultCredentialsError:
        logging.error(
            "Insufficient permissions for gcloud. Run `gcloud auth application-default login`.")
    except Exception as e:
        logging.error(e)


def options_handler(args=None):
    parser = argparse.ArgumentParser(
        description='Utility for upsert secrets to Google Secret Manager. '
                    'Docs: https://confluence-dc.paloaltonetworks.com/display/DemistoContent/Google+Secret+Manager+-+User+Guide')
    parser.add_argument('-gpid', '--gsm_project_id',
                        help='The project id in GCP.', required=False)
    parser.add_argument('-secret', '--secret_name', help='The secret id.')
    parser.add_argument('--deactivate', type=bool, action=argparse.BooleanOptionalAction, required=False, default=False,
                        help='Whether to deactivate the secret. This will remove expiration dates if found.')
    parser.add_argument('-ce', '--credential_expiration',
                        help='The expiration time of the instance\'s credentials in the secret, matching format: yyyy-mm-dd.')
    parser.add_argument('-le', '--license_expiration',
                        help='The expiration time of the product\'s license, matching format: yyyy-mm-dd.')
    parser.add_argument('-cl', '--centrify', required=False,
                        help='The secret link in Centrify Vault.')
    parser.add_argument('--jira_link', required=False,
                        help='The link of the secret updating request.')
    parser.add_argument('--skip_reason', required=False,
                        help='A skipping reason to add.')

    options = parser.parse_args(args)

    return options


if __name__ == '__main__':
    options = options_handler()
    run(options)

