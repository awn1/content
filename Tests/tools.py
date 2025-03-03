import argparse

import requests

from SecretActions.google_secret_manager_handler import get_secrets_from_gsm


def get_integration_params(options: argparse.Namespace, instance_name: str) -> dict:
    """
    Returns the integration parameters by instance name or name.

    Args:
         integration_secrets_path (str): path to integration parameters
         instance_name (str): the name of the instance to retrieve

    Returns:
        dict: the params of the requested instance name
    """
    integrations_instance_data = get_secrets_from_gsm(options).get("integrations") or []

    for integration_instance in integrations_instance_data:
        if integration_instance.get("instance_name") == instance_name or integration_instance.get("name") == instance_name:
            return integration_instance.get("params")

    raise ValueError(f"Could not find integration parameters for {instance_name}")


def get_json_response(_response: requests.Response) -> dict:
    try:
        return _response.json()
    except ValueError as e:
        raise ValueError(f"Could not parse {_response.text}, error: {e}")
