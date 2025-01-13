import argparse
import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from SecretActions.google_secret_manager_handler import ExpirationData, GoogleSecreteManagerModule

DEV_PROJECT_ID = "269994096945"
DATE_FORMAT = "%Y-%m-%d"


def create_report(expiration_date: str, records: list[dict]) -> str:
    current_date = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"Creating report for {current_date}")

    env = Environment(loader=FileSystemLoader("SecretActions/SecretExpirationReport/Files/"))
    template = env.get_template("ReportTemplate.html")
    logging.info("Successfully loaded template.")
    content = template.render(records=records, expiration_date=expiration_date, current_date=current_date)
    logging.info("Successfully rendered report.")
    return content


def format_secrets_to_dict(records: list[object]) -> list:
    """Get list of secrets and flats it into a list of dictionaries by our needs.

    Args:
        records (list[object]): Get a list of secrets objects
    Returns:
        list: _description_
    """
    logging.info("Flattening the metadata.")
    formatted_records = []
    for item in records:
        new_item = {}
        full_path = Path(item.name)
        short_name = full_path.name
        if "__" in short_name:
            integration_name, instance_name = short_name.split("__")
            new_item["Integration Name"] = integration_name
            new_item["Instance Name"] = instance_name

        new_item["name"] = short_name
        new_item["Full Path"] = full_path
        new_item["status"] = "active"
        new_item[ExpirationData.CREDS_EXPIRATION_LABEL_NAME] = ""
        new_item[ExpirationData.LICENSE_EXPIRATION_LABEL_NAME] = ""
        new_item = new_item | dict(item.labels)

        formatted_records.append(new_item)
    return formatted_records


def get_soon_to_expire_secrets(gsm_client: GoogleSecreteManagerModule, expiration_date: str) -> list[dict]:
    """
    Args:
        gsm_client (GoogleSecreteManagerModule): Google Secret Manager Client
        expiration_date (str): A date to query all secrets by.

    Returns:
        list[dict]: Query the project secrets by metadata labels of expiration.
    """
    logging.info(f"getting soon to expire secrets for {expiration_date}.")

    q = (
        f"(labels.{ExpirationData.CREDS_EXPIRATION_LABEL_NAME}<{expiration_date} OR "
        f"labels.{ExpirationData.LICENSE_EXPIRATION_LABEL_NAME}<{expiration_date})"
    )

    data = gsm_client.list_secrets_metadata_by_query(q)
    logging.info(f"Successfully queried the project. {len(data)} items were found for query: {q}")

    extracted_data = format_secrets_to_dict(data)
    return extracted_data


def run(options: argparse.Namespace):
    project_id = options.gsm_project_id if options.gsm_project_id else DEV_PROJECT_ID
    gsm_client = (
        GoogleSecreteManagerModule(options.service_account, project_id)
        if options.service_account
        else GoogleSecreteManagerModule(project_id=project_id)
    )
    expiration_date = GoogleSecreteManagerModule.GoogleSecretTools.calculate_expiration_date(options.expiration)
    secrets = get_soon_to_expire_secrets(gsm_client, expiration_date)
    report = create_report(expiration_date, secrets)

    with open(options.output_path, "w") as f:
        f.write(report)


def options_handler(args=None):
    parser = argparse.ArgumentParser(
        description="Utility for upsert secrets to Google Secret Manager. "
        "Docs: https://confluence-dc.paloaltonetworks.com/display/DemistoContent/Google+Secret+Manager+-+User+Guide"
    )
    parser.add_argument("-gpid", "--gsm_project_id", help="The project id in GCP.", required=False)
    parser.add_argument("-e", "--expiration", help="The expiration time of the secret in the following format: yyyy-mm-dd.")
    parser.add_argument(
        "-sa",
        "--service_account",
        help=(
            "Path to gcloud service account, for the flow usage. "
            "For local development use your personal account and "
            "authenticate using Google Cloud SDK by running: "
            "`gcloud auth application-default login` and leave this parameter blank. "
            "For more information see: "
            "https://googleapis.dev/python/google-api-core/latest/auth.html"
        ),
        required=False,
    )
    parser.add_argument("-o", "--output_path", required=True, help="The path to save the report to.")

    options = parser.parse_args(args)

    return options


if __name__ in ["__main__", "__builtin__", "builtins"]:
    options = options_handler()
    run(options)
