import math
import os
import json
import argparse
from glob import glob
from concurrent.futures import ThreadPoolExecutor
import subprocess
from functools import partial
import demisto_client.demisto_api
from demisto_client import generic_request_func
from slack_notifier import slack_notifier

SECRETS_KEYS = ['email', 'emailphone', 'phone']

# Items to ignore with '@' before them as well
FULL_IGNORE = ['', '?', '1E', 'CSC', 'Cybereason', 'Equifax', 'Palo Alto Networks', 'SAP', 'SOC', 'Slack', 'Support', 'Turner']

FULL_IGNORE_LOWER = [ignore.lower() for ignore in FULL_IGNORE]

# Items that will be ignored as an item but will be searched for with '@' before them
IGNORES = [
    '', '?', '1E', '542000000', '00000000000', '0000000000', '0123456789', '+44', '060606060606',

    # A
    'AACN', 'ABB', 'ADP', 'ADT', 'AFORP', 'AGEAS', 'AJ', 'AREAS', 'Abanca', 'Alstom',
    'Amway', 'Aptiv', 'Armor', 'Atlanta', 'Autodesk', 'Axity', 'Accel', 'Adidas', 'aRsaT', 'arkEma',

    # B
    'BBVA', 'BDO', 'BKM', 'BNL', 'Blackberry',

    # C
    'CAA', 'CSC', 'Cellcom', 'Comcast', 'Connect', 'Coverys', 'Cubic', 'Customer Name', 'Cybereason',
    'Cybersecurity', 'Cyclane', 'Cygate', 'Cylance', 'Cadence', 'Chicago',

    # D
    'ddd', 'dddd', 'Distribution List', 'developer',

    # E
    'E-470', 'ESRI', 'ESSEC', 'email@company.com', 'Equifax', 'elior',

    # F
    'FDNY', 'FICO', 'FQE',

    # G
    'Gaso', 'Get AS',

    # H
    'HBO', 'HNA', 'HP',

    # I
    'IDA', 'IDT', 'IEC', 'IGDAS', 'INO', 'IT Admin', 'IT Support', 'Imperva', 'InfoSec', 'Intermedia',

    # J
    'JISC Services Limited', 'JUUL', 'Joins',

    # K
    'KPMG', 'Koch',

    # L
    'LLNL', 'Licensing', 'Licensing ', 'Logitech', 'left',

    # M
    'MUTEX', 'Merck', 'Micron', 'Mission Critical',

    # N
    'NBC', 'NEDAL', 'NFL', 'NIC', 'NIL', 'NLMK', 'Natali', 'Netflix', 'Networking', 'Nike', 'Nvidia',
    'nupCo', 'Ntirety', 'null',

    # O
    'Oracle',

    # P
    'PMO', 'POC', 'Pairwise', 'Palo Alto Networks', 'PayPal', 'Pfizer', 'partner', 'Phone',

    # Q
    'QIWI',

    # R
    'Ro', 'resia',

    # S
    'SAP', 'SFPD', 'SILA', 'SIX', 'SLB', 'SOC', 'SOTEL', 'SVB', 'Salesforce.com', 'Santander', 'Slack',
    'Squadra Solutions', 'Starhub', 'Subway', 'Suez', 'Support', 'sofi',

    # T
    'TMSF', 'Team', 'Telefonica', 'Terna', 'Toyota', 'turnEr',

    # U
    'UDT', 'UVM', 'Unior', 'Upstart',

    # V
    'VPRO', 'Verizon',

    # W
    'W.I.V.', 'Workday', 'WeWork',

    # X
    'xxx@xxx.com',

    # Z
    'Zeb'
]
IGNORES_LOWER = [ignore.lower() for ignore in IGNORES]

_secrets_found = {}
_secrets_filenames = {}
_matching_secrets = {}


def option_handler():
    """Validates and parses script arguments.

    Returns:
        Namespace: Parsed arguments object.

    """
    parser = argparse.ArgumentParser(description="Secrets detection argument parsing")
    # disable-secrets-detection-start
    parser.add_argument('-c', '--content_path', help="Path to content repo", required=True)
    parser.add_argument('-u', '--host', help="URL for Demisto instance", required=True)
    parser.add_argument('-j', '--job_url', help="URL for gitlab CI job", required=False)

    # disable-secrets-detection-end
    return parser.parse_args()


def create_client(host):
    if 'SECRETS_GOLD_API_KEY_NG' in os.environ and 'SECRETS_GOLD_AUTH_ID_NG' in os.environ:
        api_key = os.environ['SECRETS_GOLD_API_KEY_NG']
        auth_id = os.environ['SECRETS_GOLD_AUTH_ID_NG']
    else:
        raise Exception('Content Gold API key and auth ID were not provided.')

    client = demisto_client.configure(base_url=host, api_key=api_key, auth_id=auth_id)

    return client


def get_data_from_cs_demisto_list(client):
    body, status_code, _ = generic_request_func(self=client, method='GET', path='/lists')

    lists = eval(body)

    for demisto_list in lists:
        if demisto_list.get('id', '') == 'CustomerSecrets':
            return demisto_list.get('data', '')

    raise Exception('There was no blacklist data provided, therefore no secrets were found.')


def get_secrets_from_raw_data(raw_blacklist_data):
    try:
        raw_blacklist_data = json.loads(raw_blacklist_data)
    except Exception as e:
        raise Exception('Could not parse CustomerSecrets as JSON, please verify the list at '
                        'https://portal.demisto.works/acc_Issues#/settings/lists - ' + str(e))

    secrets = {'compute.amazonaws.com', 'content.demisto.works'}

    def add_value_to_set(value_to_add):
        if not value_to_add:
            return

        if value_to_add.lower().strip() not in IGNORES_LOWER:
            secrets.add(value_to_add)
        elif value_to_add.lower().strip() not in FULL_IGNORE_LOWER:
            secrets.add('@' + ''.join(value_to_add.split()))

    for item in raw_blacklist_data:
        for a in item.get('customercontacts', []):
            for key, value in a.items():
                if key in SECRETS_KEYS:
                    add_value_to_set(value)

        if 'customername' in item.keys():
            add_value_to_set(item.get('customername'))

        if 'name' in item.keys():
            add_value_to_set(item.get('name'))

    return list(secrets)


def parallel_secrets_detection(packs_paths, secrets_data):
    with ThreadPoolExecutor() as executor:
        executor.map(partial(search_secrets_in_pack, secrets_data=secrets_data), packs_paths)

    return any(_secrets_found.values()), sum(_secrets_filenames.values(), []), sum(_matching_secrets.values(), [])


def is_substring_of_file_path_part(potential_secret: str, files_path_parts: set):
    """
    Check if the given potential secret is a substring of one of the given files path parts.

    Args:
        potential_secret: A potential secret to check whether it is a real secret
        files_path_parts: The files path parts of files that changed within the same path as the file that the secret was found in

    For more information see jira issue CIAC-2934.
    """
    potential_secret = potential_secret.lower()
    for path_part in files_path_parts:
        if potential_secret in path_part.lower():
            return True
    return False


def get_path_parts_to_ignore_substring_secrets(pack_path: str) -> set:
    """
    Creates and returns a set of all file names in the given pack.
    Ignores folder names and file extensions.

    Args:
        pack_path: The path of the pack to get its file names

    Returns: A set of all files names in this pack
    """
    pack_name = pack_path.split('Packs/')[1].split('/')[0] if 'Packs' in pack_path else pack_path.split('/')[0]
    files_path_parts = {pack_name}

    for root, dirs, files in os.walk(pack_path):
        for filename in files:
            files_path_parts.add(filename.split('.')[0])

    files_path_parts.discard('')
    return files_path_parts


def search_secrets_in_pack(pack_path, secrets_data: set):
    amount_of_secrets = len(secrets_data)
    amount_of_chunks = math.ceil(amount_of_secrets / 100)
    secrets_chunks = [[] for i in range(amount_of_chunks)]

    for index, secret in enumerate(secrets_data):
        secrets_chunks[index % amount_of_chunks].append(secret)

    all_out_results = list()

    for chunk in secrets_chunks:
        chunk_blacklist_data = '"' + '\\|'.join(chunk) + '"'
        chunk_blacklist_data = chunk_blacklist_data.replace('*', '').encode('utf-8')

        process_result = subprocess.Popen(
            [
                'grep', '-r', '-i', '-I', '-o', '-b', '-n',
                '--exclude=integration_commands.json',
                '--exclude=integration_search.json',
                '--exclude=package-lock.json',
                chunk_blacklist_data,
                pack_path,
            ],
            stdout=subprocess.PIPE
        )
        out, err = process_result.communicate()

        if out:
            all_out_results += out.decode('utf-8').split('\n')

    secrets_found = False
    secrets_filenames = []
    matching_secrets = []
    if all_out_results:
        files_path_parts: set = get_path_parts_to_ignore_substring_secrets(pack_path)

        for line in all_out_results:
            data = str(line).rsplit(':', 1)
            if len(data) > 1:
                secret_file = data[0]
                secret_found = data[1]
                if not is_secret_in_secret_ignore(pack_path, secret_found) and \
                        not is_substring_of_file_path_part(secret_found, files_path_parts) and \
                        '.secrets-ignore' not in secret_file:
                    secrets_found = True
                    secrets_filenames.append(secret_file)
                    matching_secrets.append(secret_found)

    _secrets_found[pack_path] = secrets_found
    _secrets_filenames[pack_path] = secrets_filenames
    _matching_secrets[pack_path] = matching_secrets


def is_secret_in_secret_ignore(pack_path, potential_secret: str):
    """
    The secrets list should ignore secrets that were declared in the given packs' secrets ignore file.
    For more information see issue 33505.
    As for the parallel run, we should ignore secrets that already appear in secrets-ignore file but were found with
    the char: '"' before or after the word.
    """
    secrets_ignore_data = ''
    with open(f'{pack_path}/.secrets-ignore', 'r') as f:
        secrets_ignore_data = f.read()

    if secrets_ignore_data:
        for ignored_secret in secrets_ignore_data.split('\n'):
            if ignored_secret.lower() == potential_secret.lower().strip('\"'):
                return True
    return False


def convert_filenames_to_content_links(secrets_filenames):
    """
    :param secrets_filenames: full links to content-test-conf repo of the secrets that were found. For example,
    home/runner/work/content-test-conf/content-test-conf/content/Packs/....
    :return: links_to_content (list): List that includes only the part of the link '/Packs....' .
    """
    links_to_content = []
    for file_name in secrets_filenames:
        file_name_path_in_content = file_name.split("Packs")[1]
        links_to_content.append(f"/Packs{file_name_path_in_content}")
    return links_to_content


def main():
    options = option_handler()
    host = options.host
    content_root_dir = options.content_path
    ci_job_url = options.job_url
    slack_token = os.environ['SLACK_TOKEN']

    try:
        client = create_client(host)
        raw_blacklist_data = get_data_from_cs_demisto_list(client)
        blacklist_data = get_secrets_from_raw_data(raw_blacklist_data)

        packs_dirs_list = glob(os.path.join(content_root_dir, "Packs/*"))
        secrets_found, secrets_filenames, matching_secrets = parallel_secrets_detection(packs_dirs_list, blacklist_data)

        if not secrets_found:
            slack_notifier(slack_token=slack_token, job_url=ci_job_url,
                           message='No secrets have been found in content repository.', success=True)
            exit(0)

        else:
            links_to_content = convert_filenames_to_content_links(secrets_filenames)
            slack_notifier(slack_token=slack_token, secrets_filenames=links_to_content, matching_secrets=matching_secrets,
                           job_url=ci_job_url)
            exit(1)

    except Exception as e:
        print(e)
        slack_notifier(slack_token=slack_token, job_url=ci_job_url, message=str(e))
        exit(1)


if __name__ == '__main__':
    main()
