import argparse
import os

import json5
import pathlib
import yaml

from Tests.scripts.collect_tests.path_manager import PathManager
from Tests.scripts.collect_tests.utils import find_pack_folder
from Tests.scripts.google_secret_manager_handler import GoogleSecreteManagerModule, FilterLabels, FilterOperators
from Tests.scripts.utils import logging_wrapper as logging
from pathlib import Path

# The default previous commit branch to check for when getting the difference from master using git
PREVIOUS_COMMIT = 'origin/master'


def get_changed_files(branch_name: str, repo) -> list[str]:
    """
    Gets the branch difference from master using git diff
    :param branch_name: the name of the branch of the PR
    :param repo: The git repo object
    :return: a list with the changed files
    """

    previous_commit = PREVIOUS_COMMIT
    current_commit = branch_name

    if branch_name == 'master':
        current_commit, previous_commit = tuple(repo.iter_commits(max_count=2))

    diff = repo.git.diff(f'{previous_commit}...{current_commit}', '--name-status')

    return find_files_diff(diff)


def find_files_diff(diff: str) -> list[str]:
    """
    Gets the branch difference from master using git diff
    :param diff: The differences found by the git command
    :return: a list with the changed files
    """
    changed_files: list[str] = []
    # diff is formatted as `M  foo.json\n A  bar.py\n ...`, turning it into ('foo.json', 'bar.py', ...).
    for line in diff.splitlines():
        match len(parts := line.split('\t')):
            case 2:
                git_status, file_path = parts
            case 3:
                git_status, old_file_path, file_path = parts  # R <old location> <new location>

                if git_status.startswith('R'):
                    git_status = 'M'

            case _:
                logging.error(f'unexpected line format '
                              f'(expected `<modifier>\t<file>` or `<modifier>\t<old_location>\t<new_location>`'
                              f', got {line}')
                continue

        if git_status not in {'A', 'M', 'D', }:
            logging.error(f'unexpected {git_status=}, considering it as <M>odified')

        changed_files.append(file_path)
    return changed_files


def get_secrets_from_gsm(branch_name: str, options: argparse.Namespace, yml_pack_ids: list[str]) -> dict:
    """
    Gets the dev secrets and main secrets from GSM and merges them
    :param branch_name: the name of the branch of the PR
    :param options: the parsed parameter for the script
    :param yml_pack_ids: a list of IDs of changed integrations
    :return: the list of secrets from GSM to use in the build
    """
    secret_conf = GoogleSecreteManagerModule(options.service_account)
    labels_filter_master = {FilterLabels.SECRET_ID: FilterOperators.NOT_NONE,
                            FilterLabels.IGNORE_SECRET: FilterOperators.NONE,
                            FilterLabels.SECRET_MERGE_TIME: FilterOperators.NONE,
                            FilterLabels.IS_DEV_BRANCH: FilterOperators.NONE}

    branch_name_converted = GoogleSecreteManagerModule.convert_to_gsm_format(branch_name)
    labels_filter_branch = {FilterLabels.SECRET_ID: FilterOperators.NOT_NONE,
                            FilterLabels.IGNORE_SECRET: FilterOperators.NONE,
                            FilterLabels.SECRET_MERGE_TIME: FilterOperators.NONE,
                            FilterLabels.IS_DEV_BRANCH: FilterOperators.NOT_NONE,
                            FilterLabels.BRANCH_NAME: f'{FilterOperators.EQUALS}"{branch_name_converted}"'}

    master_secrets = secret_conf.list_secrets(options.gsm_project_id_prod, labels_filter_master,
                                              with_secrets=True)
    branch_secrets = secret_conf.list_secrets(options.gsm_project_id_dev, labels_filter_branch,
                                              with_secrets=True)
    if branch_secrets:
        for dev_secret in branch_secrets:
            replaced = False
            instance = dev_secret.get('instance_name', 'no_instance_name')
            for i in range(len(master_secrets)):
                if dev_secret['name'] == master_secrets[i]['name'] and master_secrets[i].get('instance_name',
                                                                                             'no_instance_name') == instance:
                    master_secrets[i] = dev_secret
                    replaced = True
                    break
            # If the dev secret is not in the changed packs it's a new secret
            if not replaced:
                master_secrets.append(dev_secret)

    secret_file = {
        "username": options.user,
        "userPassword": options.password,
        "integrations": master_secrets
    }
    return secret_file


def write_secrets_to_file(options: argparse.Namespace, secrets: dict):
    """
    Writes the secrets we got from GSM to a file for the build
    :param options: the parsed parameter for the script
    :param secrets: a list of secrets to be used in the build
    """
    with open(options.json_path_file, 'w') as secrets_out_file:
        try:
            secrets_out_file.write(json5.dumps(secrets, quote_keys=True))
        except Exception as e:
            logging.error(f'Could not save secrets file, malformed json5 format, the error is: {e}')
    logging.info(f'saved the json file to: {options.json_path_file}')


def get_yml_pack_ids(changed_packs: list[str]) -> list[str]:
    """
    Gets the changed integration IDs from the YML file
    :param changed_packs: a list of changed packs in the current branch
    :return: the list of IDs of integrations to search secrets for
    """
    yml_ids = []
    for changed_pack in changed_packs:
        root_dir = Path(changed_pack)
        root_dir_instance = pathlib.Path(root_dir)
        yml_files = [item.name for item in root_dir_instance.glob("*") if str(item.name).endswith('yml')]
        for yml_file in yml_files:
            with open(f'{changed_pack}/{yml_file}', "r") as stream:
                try:
                    yml_obj = yaml.safe_load(stream)
                    yml_ids.append(yml_obj['commonfields']['id'])
                except yaml.YAMLError as exc:
                    logging.error(f'Could not extract ID from {yml_file}: {exc}')
    return yml_ids


def get_changed_packs(changed_files: list[str]) -> list[str]:
    """
    Gets the changed packs path
    :param changed_files: a list of changed file from git diff in the current branch
    :return: the list of path for the changed packs
    """

    test_changed = set()
    changed_integrations = []
    # Create a set of all the changed packs
    for f in changed_files:
        path = Path(f)
        # If not a pack find_pack_folder throws an exception
        try:
            changed = find_pack_folder(path)
            test_changed.add(f'{Path(__file__).absolute().parents[2]}/{changed}')
        except Exception as exc:
            logging.info(f'Skipped {path}, got error: {exc}')
            continue
    # create a list of all the changed integrations

    for changed_pack_path in test_changed:
        if 'Integrations' in os.listdir(changed_pack_path):
            integrations_path = f'{changed_pack_path}/Integrations'
            integrations = os.listdir(integrations_path)
            changed_integrations.extend([f'{integrations_path}/{i}' for i in integrations])
        else:
            logging.info(f'Skipped {path}, there is no integration in pack, cant get the secret ID')
    return changed_integrations


def get_test_integrations_ids(ids: list[str]) -> list[str]:
    conf_path = "Tests/conf.json"
    ids_to_add = set(ids)
    try:
        with open(conf_path, "r") as file:
            data = json5.load(file)
            tests = data['tests']
            for test in tests:
                if 'integrations' in test and isinstance(test['integrations'], list) and len(test['integrations']) > 1:
                    test_ids = test['integrations']
                    if any([i in ids for i in test_ids]):
                        ids_to_add |= set(test_ids)
    except Exception as exc:
        logging.error(f'Could not get additional IDs from conf.json, encountered an error: {exc}')
        return ids
    return list(ids_to_add)


def run(options: argparse.Namespace):
    paths = PathManager(Path(__file__).absolute().parents[2])
    branch_name = paths.content_repo.active_branch.name
    changed_packs = []
    yml_pack_ids = []
    # Don't get specific secrets for a branch, but the build won't fail and secrets from the main store will be used
    try:
        changed_files = get_changed_files(branch_name, paths.content_repo)
        logging.info(f'Changed files from git = {changed_files}')
        changed_packs.extend(get_changed_packs(changed_files))
        logging.info(f'Changed packs from changed_files = {changed_packs}')
        yml_pack_ids.extend(get_yml_pack_ids(changed_packs))
        yml_pack_ids = get_test_integrations_ids(yml_pack_ids)
        logging.info(f'Changed integrations IDs = {yml_pack_ids}')
    except Exception as e:
        logging.info(
            f'Could not get specific dev secrets for the branch {branch_name}, received the error {e}, using main store secrets')
    secrets_file = get_secrets_from_gsm(branch_name, options, yml_pack_ids)
    logging.info(f'Using {len(secrets_file["integrations"])} secrets')
    names = [s.get('name') for s in secrets_file["integrations"]]
    logging.info(f'the names: {names}')
    write_secrets_to_file(options, secrets_file)


def options_handler(args=None) -> argparse.Namespace:
    """
    Parse  the passed parameters for the script
    :param args: a list of arguments to add
    :return: the parsed arguments that were passed to the script
    """
    parser = argparse.ArgumentParser(description='Utility for Importing secrets from Google Secret Manager.')
    parser.add_argument('-gpidd', '--gsm_project_id_dev', help='The project id for the GSM dev.')
    parser.add_argument('-gpidp', '--gsm_project_id_prod', help='The project id for the GSM prod.')
    parser.add_argument('-u', '--user', help='the user name for our build.')
    parser.add_argument('-p', '--password', help='The password for our build.')
    parser.add_argument('-sf', '--json_path_file', help='Path to the secret json file.')
    # disable-secrets-detection-start
    parser.add_argument('-sa', '--service_account',
                        help=("Path to gcloud service account, for circleCI usage. "
                              "For local development use your personal account and "
                              "authenticate using Google Cloud SDK by running: "
                              "`gcloud auth application-default login` and leave this parameter blank. "
                              "For more information see: "
                              "https://googleapis.dev/python/google-api-core/latest/auth.html"))
    # disable-secrets-detection-end
    options = parser.parse_args(args)

    return options


if __name__ == '__main__':
    options = options_handler()
    run(options)
