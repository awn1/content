import json
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from tempfile import mkdtemp
from typing import Any
from urllib.parse import urljoin

import demisto_client
import requests
from demisto_client.demisto_api.api.default_api import DefaultApi as DemistoClient
from demisto_client.demisto_api.rest import ApiException
from packaging.version import Version
from urllib3.exceptions import HTTPError, HTTPWarning

from Tests.Marketplace.marketplace_constants import Metadata
from Tests.Marketplace.upload_packs import extract_packs_artifacts
from Tests.scripts.utils import logging_wrapper as logging

ALREADY_IN_PROGRESS = "operation is already in progress"


def get_json_file(path):
    with open(path) as json_file:
        return json.loads(json_file.read())


def generic_request_with_retries(client: DemistoClient,
                                 retries_message: str,
                                 exception_message: str,
                                 prior_message: str,
                                 path: str,
                                 method: str,
                                 request_timeout: int | None = None,
                                 accept: str = 'application/json',
                                 body: Any | None = None,
                                 response_type: str | None = 'str',
                                 attempts_count: int = 5,
                                 sleep_interval: int = 60,
                                 should_try_handler: Callable[[], bool] | None = None,
                                 success_handler: Callable[[Any], Any] | None = None,
                                 api_exception_handler: Callable[[ApiException, int], Any] | None = None,
                                 http_exception_handler: Callable[[HTTPError | HTTPWarning], Any] | None = None):
    """

    Args:
        response_type: response type to use.
        body: request body.
        client: demisto client.
        retries_message: message to print after failure when we have more attempts.
        exception_message: message to print when we get and exception that is not API or HTTP exception.
        prior_message: message to print when a new retry is made.
        path: endpoint to send request to.
        method: HTTP method to use.
        request_timeout: request param.
        accept: request param.
        attempts_count: number of total attempts made.
        sleep_interval: sleep interval between attempts.
        should_try_handler: a method to determine if we should send the next request.
        success_handler: a method to run in case of successful request (according to the response status).
        api_exception_handler: a method to run in case of api exception.
        http_exception_handler: a method to run in case of http exception

    Returns: True if the request succeeded and status in case of waiting_for_process_to_end

    """
    try:
        for attempts_left in range(attempts_count - 1, -1, -1):
            try:
                if should_try_handler and not should_try_handler():
                    # if the method exist, and we should not try again.
                    return True, None

                # should_try_handler return True, we are trying to send request.
                logging.info(f"{prior_message}, attempt: {attempts_count - attempts_left}/{attempts_count}")
                response, status_code, headers = demisto_client.generic_request_func(client,
                                                                                     path=path,
                                                                                     method=method,
                                                                                     accept=accept,
                                                                                     body=body,
                                                                                     response_type=response_type,
                                                                                     _request_timeout=request_timeout)

                if 200 <= status_code < 300 and status_code != 204:
                    if success_handler:
                        # We have a method to run as we were returned a success status code.
                        return success_handler(response)

                    # No handler, just return True.
                    return True, None

                else:
                    err = f"Got {status_code=}, {headers=}, {response=}"

                if not attempts_left:
                    # No attempts left, raise an exception that the request failed.
                    raise Exception(err)

                logging.warning(err)

            except ApiException as ex:
                if api_exception_handler:
                    body = api_exception_handler(ex, attempts_left)
                if not attempts_left:  # exhausted all attempts, understand what happened and exit.
                    raise Exception(f"Got status {ex.status} from server, message: {ex.body}, headers: {ex.headers}") from ex
                logging.debug(f"Process failed, got error {ex}")
            except (HTTPError, HTTPWarning) as http_ex:
                if http_exception_handler:
                    http_exception_handler(http_ex)
                if not attempts_left:  # exhausted all attempts, understand what happened and exit.
                    raise Exception("Failed to perform http request to the server") from http_ex
                logging.debug(f"Process failed, got error {http_ex}")

            # There are more attempts available, sleep and retry.
            logging.debug(f"{retries_message}, sleeping for {sleep_interval} seconds.")
            time.sleep(sleep_interval)
    except Exception as e:
        logging.exception(f'{exception_message}. Additional info: {e!s}')
    return False, None


def get_updating_status(client: DemistoClient,
                        attempts_count: int = 5,
                        sleep_interval: int = 60,
                        request_timeout: int = 300,
                        ) -> tuple[bool, bool | None]:

    def success_handler(response):
        updating_status = 'true' in str(response).lower()
        logging.info(f"Got updating status: {updating_status}")
        return True, updating_status

    return generic_request_with_retries(client=client,
                                        success_handler=success_handler,
                                        retries_message="Failed to get installation/update status",
                                        exception_message="The request to get update status has failed",
                                        prior_message="Getting installation/update status",
                                        path='/content/updating',
                                        method='GET',
                                        attempts_count=attempts_count,
                                        sleep_interval=sleep_interval,
                                        request_timeout=request_timeout,
                                        )


def wait_until_not_updating(client: DemistoClient,
                            attempts_count: int = 2,
                            sleep_interval: int = 30,
                            maximum_time_to_wait: int = 600,
                            ) -> bool:
    """

    Args:
        client (demisto_client): The client to connect to.
        attempts_count (int): The number of attempts to install the packs.
        sleep_interval (int): The sleep interval, in seconds, between install attempts.
        maximum_time_to_wait (int): The maximum time to wait for the server to exit the updating mode, in seconds.
    Returns:
        Boolean - If the operation succeeded.

    """
    end_time = datetime.utcnow() + timedelta(seconds=maximum_time_to_wait)
    while datetime.utcnow() <= end_time:
        success, updating_status = get_updating_status(client)
        if success:
            if not updating_status:
                return True
            logging.debug(f"Server is still installation/updating status, sleeping for {sleep_interval} seconds.")
            time.sleep(sleep_interval)
        else:
            if attempts_count := attempts_count - 1:
                logging.debug(f"failed to get installation/updating status, sleeping for {sleep_interval} seconds.")
                time.sleep(sleep_interval)
            else:
                logging.info("Exiting after exhausting all attempts")
                return False
    logging.info(f"Exiting after exhausting the allowed time:{maximum_time_to_wait} seconds")
    return False


def send_api_request_with_retries(
    base_url: str,
    retries_message: str,
    exception_message: str,
    success_message: str,
    prior_message: str,
    endpoint: str,
    method: str,
    params: dict | None = None,
    headers: dict | None = None,
    request_timeout: int | None = None,
    accept: str = 'application/json',
    body: Any | None = None,
    attempts_count: int = 5,
    sleep_interval: int = 60,
    should_try_handler: Callable[[Any], bool] | None = None,
    success_handler: Callable[[Any], Any] | None = None,
    api_exception_handler: Callable[[ApiException, int], Any] | None = None,
    http_exception_handler: Callable[[HTTPError | HTTPWarning], Any] | None = None
):
    """
    Args:
        body: request body.
        base_url: base url to send request
        headers: headers for the request.
        success_message:  message to print after success response.
        retries_message: message to print after failure when we have more attempts.
        exception_message: message to print when we get and exception that is not API or HTTP exception.
        prior_message: message to print when a new retry is made.
        endpoint: endpoint to send request to.
        method: HTTP method to use.
        params: api request params.
        request_timeout: request param.
        accept: request param.
        attempts_count: number of total attempts made.
        sleep_interval: sleep interval between attempts.
        should_try_handler: a method to determine if we should send the next request.
        success_handler: a method to run in case of successful request (according to the response status).
        api_exception_handler: a method to run in case of api exception.
        http_exception_handler: a method to run in case of http exception

    Returns: True if the request succeeded

    """
    headers = headers if headers else {}
    headers['Accept'] = accept
    response = None
    url_path = urljoin(base_url, endpoint)
    try:
        for attempts_left in range(attempts_count - 1, -1, -1):
            try:
                if should_try_handler and not should_try_handler(response):
                    # if the method exist, and we should not try again.
                    return True

                logging.info(f"{prior_message}, attempt: {attempts_count - attempts_left}/{attempts_count}")
                response = requests.request(
                    method=method,
                    url=url_path,
                    verify=False,
                    params=params,
                    data=body,
                    headers=headers,
                    timeout=request_timeout,
                )
                if 200 <= response.status_code < 300 and response.status_code != 204:
                    logging.debug(f"Got successful response: {response.status_code=},  {response.content=}.")
                    logging.info(success_message)
                    if success_handler:
                        return success_handler(response)

                    return True

                else:
                    err = f"Got {response.status_code=}, {response.headers=}, {response.content=}"

                if not attempts_left:
                    raise Exception(err)

                logging.warning(f"Got error: {err}")

            except ApiException as ex:
                if api_exception_handler:
                    api_exception_handler(ex, attempts_left)
                if not attempts_left:
                    raise Exception(f"Got status {ex.status} from server, message: {ex.body}, headers: {ex.headers}") from ex
                logging.debug(f"Process failed, got error {ex}")
            except (HTTPError, HTTPWarning) as http_ex:
                if http_exception_handler:
                    http_exception_handler(http_ex)
                if not attempts_left:
                    raise Exception("Failed to perform http request to the server") from http_ex
                logging.debug(f"Process failed, got error {http_ex}")

            logging.debug(f"{retries_message}, sleeping for {sleep_interval} seconds.")
            time.sleep(sleep_interval)
    except Exception as e:
        logging.exception(f'{exception_message}. Additional info: {e!s}')
    return False


def fetch_pack_ids_to_install(packs_to_install_path: str) -> list[str]:
    """
    Reads a file containing pack IDs, one per line, and returns a list of these IDs.
    Args:
        packs_to_install_path (str): The file path where the pack IDs to install are stored.
    Returns:
        list[str]: A list of pack IDs read from the file.
    """
    try:
        with open(packs_to_install_path) as pack_ids_to_install:
            packs_to_install = [pack.rstrip() for pack in pack_ids_to_install]
    except (OSError, FileNotFoundError) as e:
        logging.info(f"Error occurred while reading the file {packs_to_install_path}: {e}")
        return []

    return packs_to_install


def get_packs_with_higher_min_version(packs_names: set[str],
                                      server_numeric_version: str,
                                      extract_content_packs_path: str | None = None) -> set[str]:
    """
    Return a set of packs that have higher min version than the server version.

    Args:
        packs_names (Set[str]): A set of packs to install.
        server_numeric_version (str): The server version.
        extract_content_packs_path (str | None): Path to a temporary folder with extracted content packs metadata.

    Returns:
        (Set[str]): The set of the packs names that supposed to be not installed because
                    their min version is greater than the server version.
    """
    if not extract_content_packs_path:
        artifacts_folder_server_type = os.getenv('ARTIFACTS_FOLDER_SERVER_TYPE')
        extract_content_packs_path = mkdtemp()
        packs_artifacts_path = f'{artifacts_folder_server_type}/content_packs.zip'
        extract_packs_artifacts(packs_artifacts_path, extract_content_packs_path)

    packs_with_higher_version = set()
    for pack_name in packs_names:
        pack_metadata = get_json_file(f"{extract_content_packs_path}/{pack_name}/metadata.json")
        server_min_version = pack_metadata.get(Metadata.SERVER_MIN_VERSION,
                                               pack_metadata.get('server_min_version', Metadata.SERVER_DEFAULT_MIN_VERSION))

        if 'Master' not in server_numeric_version and Version(server_numeric_version) < Version(server_min_version):
            packs_with_higher_version.add(pack_name)
            logging.info(f"Found pack '{pack_name}' with min version {server_min_version} that is "
                         f"higher than server version {server_numeric_version}")

    return packs_with_higher_version