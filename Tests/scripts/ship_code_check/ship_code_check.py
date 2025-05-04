import logging
import shutil
from Tests.scripts.utils.log_util import install_logging
import demistomock as demisto
from CommonServerPython import *  # noqa # pylint: disable=unused-wildcard-import
from CommonServerUserPython import *  # noqa

from typing import Dict, Tuple
import traceback
import concurrent.futures
import filecmp
import hashlib
import io
import json
import os
from threading import Lock
from zipfile import ZipFile
import os.path
from demisto_sdk.commands.common.constants import MarketplaceVersionToMarketplaceName
from packaging import version
from google.cloud import storage
import difflib
import urllib3
import yaml
import subprocess


urllib3.disable_warnings()

''' CONSTANTS '''

DATE_FORMAT = '%Y-%m-%dT%H:%M:%SZ'  # ISO8601 format with UTC, default in XSOAR
HOME_FOLDER_DIR = '/var/lib/demisto'
COMMAND_TEMP_FOLDERS_DIR = '/var/tmp/check_content_code'
TARGET_PATH_FOR_DATA_FROM_GCS = f'{COMMAND_TEMP_FOLDERS_DIR}/from_gcs'
TARGET_PATH_FOR_CONTENT_REPO = f'{COMMAND_TEMP_FOLDERS_DIR}/from_git'
CONTENT_REPO_URL = 'https://github.com/demisto/content'
CONTENT_ARTIFACTS_DIR = f'{TARGET_PATH_FOR_CONTENT_REPO}/content_artifacts_dir'

INTEGRATIONS_DIR = 'Integrations'
SCRIPTS_DIR = 'Scripts'

FILES_ONLY_IN_BUCKET = 'only_in_bucket'
FILES_ONLY_IN_SOURCE_CODE = 'only_in_src_code'
DIFFERENT_FILES = 'different_files'
NOT_UPLOADED_IN_LAST_FLOW = 'not_uploaded_in_last_flow'
DIFFERENT_FILES_RESULTS = 'file_results'

BUF_SIZE = 1000

IGNORED_PACK_NAMES = ['builds']
IGNORED_DIR_NAMES = ('readme_images', 'integration_description_images')

# swap between the keys and the values for MarketplaceVersionToMarketplaceName
BUCKETS = []
BUCKET_TO_MARKETPLACE = dict((v, k) for k, v in MarketplaceVersionToMarketplaceName.items())
''' HELPER FUNCTIONS '''


def compare_files_hashes(src_dir: str, gcs_dir: str, common_files: list, result: dict,
                         is_pack_uploaded: bool) -> bool:
    """
    Compare all the common files in the given two dirs and update the result dictionary.

    :type src_dir: ``str``
    :param src_dir: repo dirs path
    :type gcs_dir: ``str``
    :param gcs_dir: bucket dirs path
    :type common_files: ``list``
    :param common_files: list of the common files in the dir to compare
    :type result: ``dict``
    :param result: result summary of the different files
    :type is_pack_uploaded: ``bool``
    :param is_pack_uploaded: true if file was uploaded in the last upload pipeline, else- false

    :return: true if files are equals, else- false
    :rtype: ``bool``
   """
    for file in common_files:
        src_file_hash = get_file_hash(os.path.join(src_dir, file))
        gcs_file_hash = get_file_hash(os.path.join(gcs_dir, file))

        if src_file_hash != gcs_file_hash:
            demisto.debug(f'Src file hash: {src_file_hash}, Gcs file hash: {gcs_file_hash}.\n')
            if is_pack_uploaded:
                with open(os.path.join(src_dir, file), mode='r', encoding='utf-8') as f:
                    src_read = f.read()
                    src_file = fileResult(filename=f'repo_{file}', data=src_read)
                with open(os.path.join(gcs_dir, file), mode='r', encoding='utf-8') as f:
                    gcs_read = f.read()
                    gcs_file = fileResult(filename=f'bucket_{file}', data=gcs_read)

                diff = difflib.unified_diff(src_read.split('\n'), gcs_read.split('\n'),
                                            fromfile=f'repo_{file}', tofile=f'bucket_{file}')
                if diff:
                    diff_text = '\n'.join(list(diff))
                    diff_file = fileResult(filename=f'{file.replace(".yml", "")}_diff.txt', data=diff_text)

                    result[DIFFERENT_FILES_RESULTS].extend([src_file, gcs_file, diff_file])
                    result[DIFFERENT_FILES].append(file)
            else:
                result[NOT_UPLOADED_IN_LAST_FLOW].append(file)
            return False

    return True


def get_file_hash(file_path: str) -> str:
    """
    returns the sha1 of a file

    :type file_path: ``list``
    :param file_path: path to file

    :return: sha1 of the file
    :rtype: ``str``
   """
    sha1 = hashlib.sha1()  # nosec
    with open(file_path, "rb") as f1:
        while True:
            data = f1.read(BUF_SIZE)
            if not data:
                break

            sha1.update(data)
    return sha1.hexdigest()


def compare_dirs(src_dir: str, gcs_dir: str, results_dict: dict, relevant_subdirs: list, is_pack_uploaded: bool,
                 bucket_name: str):
    """
    Compare all the files in the given subdir in two dirs and update the result dictionary.

    :type src_dir: ``str``
    :param src_dir: repo packs dir path
    :type gcs_dir: ``str``
    :param gcs_dir: bucket packs dir path
    :type results_dict: ``dict``
    :param results_dict: result summary of the different files
    :type relevant_subdirs: ``list``
    :param relevant_subdirs: sub dirs names to check
    :type is_pack_uploaded: ``bool``
    :param is_pack_uploaded: true if file was uploaded in the last upload pipeline, else- false
    :type bucket_name: ``str``
    :param bucket_name: name of the bucket

    :return: true if files are equals, else- false
    :rtype: ``bool``
   """

    marketplace_name = BUCKET_TO_MARKETPLACE.get(bucket_name)
    src_metadata_path = os.path.join(src_dir, 'metadata.json')

    if os.path.isfile(src_metadata_path):
        with io.open(src_metadata_path, mode='r', encoding='utf-8') as f:
            pack_metadata = json.loads(f.read())
            src_marketplaces = pack_metadata.get("marketplaces", [])
            is_pack_hidden = pack_metadata.get("hidden", False)

        # no need to compare the pack when it's hidden from the marketplace
        if is_pack_hidden:
            return

        # no need to compare the pack when it should not be in the marketplace
        if marketplace_name not in src_marketplaces:
            return

    if is_pack_uploaded:
        missing_in_bucket_key = FILES_ONLY_IN_SOURCE_CODE
    else:
        missing_in_bucket_key = NOT_UPLOADED_IN_LAST_FLOW

    for sub_dir in relevant_subdirs:
        src_subdir_path = os.path.join(src_dir, sub_dir)
        gcs_subdir_path = os.path.join(gcs_dir, sub_dir)
        if not os.path.isdir(src_subdir_path) and not os.path.isdir(gcs_subdir_path):
            return
        elif not os.path.isdir(gcs_subdir_path):
            results_dict[missing_in_bucket_key].extend(os.listdir(src_subdir_path))
            return
        elif not os.path.isdir(src_subdir_path):
            results_dict[FILES_ONLY_IN_BUCKET].extend(os.listdir(gcs_subdir_path))
            return

        dirs_cmp = filecmp.dircmp(src_subdir_path, gcs_subdir_path)
        if len(dirs_cmp.left_only) > 0:
            file_path = os.path.join(src_subdir_path, dirs_cmp.left_only[0])
            try:
                with open(file_path, 'r') as yml_file:
                    data = yaml.safe_load(yml_file)
                if not isinstance(data, dict):
                    raise ValueError()
            except Exception as e:
                demisto.error(f'Failed to open the file {file_path} error: {e}')

            marketplaces = data.get('marketplaces', [marketplace_name])

            if marketplace_name in marketplaces:
                results_dict[missing_in_bucket_key].extend(dirs_cmp.left_only)

        if len(dirs_cmp.right_only) > 0:
            results_dict[FILES_ONLY_IN_BUCKET].extend(dirs_cmp.right_only)

        compare_files_hashes(src_dir=src_subdir_path, gcs_dir=gcs_subdir_path, common_files=dirs_cmp.common_files,
                             result=results_dict, is_pack_uploaded=is_pack_uploaded)


def extract_pack(packs_path: str) -> str:
    """ unzip zipped pack.

    :type packs_path: ``list``
    :param packs_path: path to zipped folder

    :return: path to extracted pack folder
    :rtype: ``str``
    """
    extracted_pack_path = packs_path.rstrip(".zip")
    # check if pack is already extracted
    if not os.path.isdir(extracted_pack_path):
        with ZipFile(packs_path) as packs_artifacts:
            packs_artifacts.extractall(extracted_pack_path)
    return extracted_pack_path


def get_latest_version(versions_list: list) -> str:
    """Finds the latest version in the list

    :type versions_list: ``list``
    :param versions_list: list of versions in the format x.x.x

    :return: latest version
    :rtype: ``str``
    """
    latest = "0"
    for v in versions_list:
        if v not in IGNORED_DIR_NAMES and version.parse(v) > version.parse(latest):
            latest = v
    return latest


def find_latest_dir_path(pack_path: str):
    if os.path.isdir(pack_path):  # only packs
        all_versions = [i for i in os.listdir(pack_path) if os.path.isdir(os.path.join(pack_path, i))]
        if all_versions:
            return os.path.join(pack_path, get_latest_version(all_versions))

    return ''


def delete_folders():
    if os.path.isdir(COMMAND_TEMP_FOLDERS_DIR):
        shutil.rmtree(COMMAND_TEMP_FOLDERS_DIR)


def compare_bucket_and_src_code(zip_packs_from_gcs_dir_path: str, zip_packs_from_src_code_dir_path: str,
                                uploaded_packs: set, bucket_name: str) -> dict:
    result_dict: dict = {FILES_ONLY_IN_BUCKET: [], FILES_ONLY_IN_SOURCE_CODE: [], DIFFERENT_FILES: [],
                         NOT_UPLOADED_IN_LAST_FLOW: [], DIFFERENT_FILES_RESULTS: []}

    demisto.debug('Comparing source code files to the files from GCS')
    # save all zip files from gcp that we have compared with source code
    checked_zip_files = set()
    for pack in os.listdir(zip_packs_from_gcs_dir_path):
        if pack in IGNORED_PACK_NAMES:
            continue

        pack_path = os.path.join(zip_packs_from_gcs_dir_path, pack)
        latest_version_path = find_latest_dir_path(pack_path)

        if not latest_version_path:
            continue

        for pack_item in os.listdir(latest_version_path):
            if pack_item.endswith(".zip"):
                pack_name = pack_item.rstrip(".zip")
                is_uploaded = pack_name in uploaded_packs
                # unzip zipped pack from gcp
                unzipped_gcp_pack_path = extract_pack(os.path.join(latest_version_path, pack_item))

                src_zip_path = os.path.join(zip_packs_from_src_code_dir_path, pack_item)
                checked_zip_files.add(pack_item)
                # check if ZIP file exist in git
                if not os.path.isfile(src_zip_path):
                    # add all integrations and scripts yaml in the missing pack to result
                    compare_dirs(src_dir="dummy_dir", gcs_dir=unzipped_gcp_pack_path, results_dict=result_dict,
                                 relevant_subdirs=[INTEGRATIONS_DIR, SCRIPTS_DIR], is_pack_uploaded=is_uploaded,
                                 bucket_name=bucket_name)
                else:
                    # unzip src zipped pack from create content artifacts
                    unzipped_src_pack_path = extract_pack(src_zip_path)

                    compare_dirs(src_dir=unzipped_src_pack_path, gcs_dir=unzipped_gcp_pack_path,
                                 results_dict=result_dict,
                                 relevant_subdirs=[INTEGRATIONS_DIR, SCRIPTS_DIR], is_pack_uploaded=is_uploaded,
                                 bucket_name=bucket_name)

    all_src_zip = set(
        pack_item for pack_item in os.listdir(zip_packs_from_src_code_dir_path) if pack_item.endswith(".zip"))
    diff = all_src_zip.difference(checked_zip_files)
    for zip_pack in diff:
        unzipped_src_pack_path = extract_pack(os.path.join(zip_packs_from_src_code_dir_path, zip_pack))
        is_uploaded = zip_pack.rstrip(".zip") in uploaded_packs
        # add all integrations and scripts yaml in the missing pack to result
        compare_dirs(src_dir=unzipped_src_pack_path, gcs_dir="dummy_dir", results_dict=result_dict,
                     relevant_subdirs=[INTEGRATIONS_DIR, SCRIPTS_DIR], is_pack_uploaded=is_uploaded,
                     bucket_name=bucket_name)
    delete_folders()
    return result_dict


def download_blob(storage_client: storage.Client, bucket_name: str, source_blob_name: str, target_folder: str):
    """download the content of the given gcs bucket

    :type storage_client: ``storage.Client``
    :param storage_client: google storage client

    :type bucket_name: ``str``
    :param bucket_name: name of the bucket

    :type source_blob_name: ``str``
    :param source_blob_name: prefix of the blob to download

    :type target_folder: ``str``
    :param target_folder: path to local folder
    """

    bucket = storage_client.bucket(bucket_name=bucket_name)
    mutex = Lock()

    def download_to_file(blob):
        if blob.name != source_blob_name:
            file_uri = "{}/{}".format(target_folder, blob.name)
            file_folder = '/'.join(file_uri.split('/')[:-1])
            with mutex:
                if not os.path.exists(file_folder):
                    os.makedirs(file_folder)
            blob.download_to_filename(file_uri)

    blobs = bucket.list_blobs(prefix=source_blob_name)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for b in blobs:
            futures.append(executor.submit(download_to_file, blob=b))
        concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_EXCEPTION)


def get_last_upload_job_results_artifacts(bucket_name: str, last_commit: str, storage_client) -> dict:
    """Returns the pack_result json file of the last running upload job from xsoar-ci-artifacts bucket

    :type bucket_name: ``str``
    :param bucket_name: name of the bucket
    :type last_commit: ``str``
    :param last_commit: last commit of upload
    :type storage_client: ``storage.Client``
    :param storage_client: storage.Client: initialized google cloud storage client.

    """

    marketplace = BUCKET_TO_MARKETPLACE.get(bucket_name)
    pack_results_path = f'content/{last_commit}/{marketplace}/packs_results_upload.json'
    bucket = storage_client.bucket(bucket_name='xsoar-ci-artifacts')
    blob = storage.Blob(pack_results_path, bucket)
    return json.loads(blob.download_as_text())


def list_uploaded_packs_from_pack_results_artifacts(pack_results_json_data: dict) -> set:
    """Extract from the packs_results_upload.json data a list of the packs that were uploaded in the last flow

    :type pack_results_json_data: ``dict``
    :param pack_results_json_data: results json file data (from upload job artifacts)

    :return: list of the packs names that were uploaded successfully
    :rtype: ``list``
    """

    packs_results = pack_results_json_data.get('upload_packs_to_marketplace_storage', {}).get('successful_packs')
    uploaded_packs = [pack_name for pack_name in packs_results if
                      packs_results.get(pack_name).get('status') == 'SUCCESS']
    return set(uploaded_packs)


def extract_commit_id_from_index_file(index_file_path: str) -> str:
    """Returns the 'commit' value  from json file

    :type index_file_path: ``str``
    :param index_file_path: path to index json file

    :return: commit id
    :rtype: ``str``
    """
    with io.open(index_file_path, mode='r', encoding='utf-8') as f:
        return json.loads(f.read()).get("commit")


def prepare_source_code_artifacts(bucket_name) -> str:
    """Runs the 'create-content-artifacts' sdk command in the downloaded content repo on the commit from
        the last running upload flow

    :return: last upload flow commit
    :rtype: ``str``
    """
    os.chdir(COMMAND_TEMP_FOLDERS_DIR)
    # extract commit id of the latest upload-flow
    last_commit = extract_commit_id_from_index_file(f'{TARGET_PATH_FOR_DATA_FROM_GCS}/content/packs/index.json')

    demisto.debug('Downloading the content repo zip from git')
    r = requests.get(f'{CONTENT_REPO_URL}/archive/{last_commit}.zip', stream=True)
    with open(f'{TARGET_PATH_FOR_CONTENT_REPO}.zip', 'wb') as fd:
        for chunk in r.iter_content(chunk_size=256):
            fd.write(chunk)

    extracted_path = extract_pack(f'{TARGET_PATH_FOR_CONTENT_REPO}.zip')
    marketplace_name = BUCKET_TO_MARKETPLACE.get(bucket_name)

    # create content artifacts locally
    demisto.debug('Creating content artifacts')

    os.rename(f'{extracted_path}/content-{last_commit}', f'{extracted_path}/content')
    os.chdir(f'{extracted_path}/content')

    packs_list = os.listdir(f'{extracted_path}/content/Packs')

    os.mkdir(f'{COMMAND_TEMP_FOLDERS_DIR}/uploadable_packs')

    for pack in packs_list:
        try:
            subprocess.run(
                ["demisto-sdk", "prepare-content", "-i",
                 f"Packs/{pack}", "-mp", marketplace_name, "-o",  # type: ignore
                 f'{COMMAND_TEMP_FOLDERS_DIR}/uploadable_packs'],
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            demisto.error(f'prepare-content for {pack} failed: {e} Error output: {e.stderr}')
        except Exception as ex:
            demisto.error(f"prepare-content for {pack} failed: {ex}")

    os.chdir(HOME_FOLDER_DIR)
    return last_commit


def check_content_shipped_code(storage_client, bucket_name) -> Tuple[Dict, list]:
    """Returns a simple python dict with the information provided
    in the input.

    :type storage_client: storage.client
    :param storage_client: google storage client
    :type bucket_name: ``str``
    :param bucket_name: name of the bucket

    :return: dict with the code check results
    :rtype: ``dict``
    :return: array with fileresults for the different files
    :rtype: ``arr``
    """
    os.mkdir(COMMAND_TEMP_FOLDERS_DIR)
    # download current content from bucket
    demisto.debug(f'Downloading content from bucket: {bucket_name}')
    os.mkdir(TARGET_PATH_FOR_DATA_FROM_GCS)

    try:
        download_blob(storage_client=storage_client, bucket_name=bucket_name, source_blob_name="content/packs/",
                      target_folder=TARGET_PATH_FOR_DATA_FROM_GCS)
    except Exception as e:
        raise Exception(f'Failed download content from bucket: {e}')

    # clone content repo and create content artifacts
    last_commit = prepare_source_code_artifacts(bucket_name)

    demisto.debug(f'Created artifacts, last commit: {last_commit}')
    demisto.debug('Getting pack_results.json file from gitlab artifacts')

    pack_results_json_data = get_last_upload_job_results_artifacts(bucket_name, last_commit, storage_client)

    if not pack_results_json_data:
        return {}, []

    uploaded_packs = list_uploaded_packs_from_pack_results_artifacts(pack_results_json_data=pack_results_json_data)

    # compare source code yaml files and yaml files from bucket
    zip_packs_from_gcs_dir_path = f'{TARGET_PATH_FOR_DATA_FROM_GCS}/content/packs'
    zip_packs_from_src_code_dir_path = f'{COMMAND_TEMP_FOLDERS_DIR}/uploadable_packs'
    files_result_summary = compare_bucket_and_src_code(zip_packs_from_gcs_dir_path, zip_packs_from_src_code_dir_path,
                                                       uploaded_packs, bucket_name)
    files_result_summary['commit'] = last_commit
    file_results = files_result_summary[DIFFERENT_FILES_RESULTS]

    del files_result_summary[DIFFERENT_FILES_RESULTS]

    files_result_summary['bucket_name'] = bucket_name

    return files_result_summary, file_results


''' COMMAND FUNCTIONS '''


def module_test(storage_client: storage.Client, bucket_name) -> str:
    """Tests API connectivity and authentication to Gitlab and google storage'

    Returning 'ok' indicates that the integration works like it is supposed to.
    Connection to the service is successful.
    Raises exceptions if something goes wrong.

    :type storage_client: storage.client
    :param storage_client: google storage client
    :type bucket_name: ``str``
    :param bucket_name: name of the bucket

    :return: 'ok' if test passed, anything else will fail the test.
    :rtype: ``str``
    """

    message: str = ''

    # verify google storage credentials
    try:
        b = storage_client.bucket(bucket_name)
        required_permissions_list = ['storage.objects.list', 'storage.objects.get']
        found_permissions = set(b.test_iam_permissions(permissions=required_permissions_list))
        required_permissions = set(required_permissions_list)
        if required_permissions.difference(found_permissions):
            message = f'{message} Google storage credentials are not valid: ' \
                      f'missing {required_permissions.difference(found_permissions)}'
    except Exception as e:
        message = f'{message} Google storage credentials are not valid: {e}'
    message = message if message else 'ok'
    return message


def check_content_shipped_code_command(storage_client, bucket_name) -> Tuple[CommandResults, list]:
    result, file_results = check_content_shipped_code(storage_client, bucket_name)

    return CommandResults(
        outputs_prefix='ContentCodeCheck',
        outputs_key_field='',
        outputs=result,
    ), file_results


def create_slack_message_command(args: dict, bucket_name):
    """Creates a formatted string out of the  result dictionary that will be sent in a slack notification

     :type args: command args
     :param args: command args
     :type bucket_name: ``str``
     :param bucket_name: name of the bucket

     :return: a formated string of the missing/ different files results.
     :rtype: ``str``
     """

    message = f'Results for *{bucket_name}* bucket:\n'
    result_dict = args.get('result_dict', {})
    commit = {result_dict.get("commit")}
    lines = []
    for key, files in result_dict.items():
        if files and key in [FILES_ONLY_IN_BUCKET, FILES_ONLY_IN_SOURCE_CODE, DIFFERENT_FILES]:
            pretty_lines = "\n".join(files)
            lines.append(f'*{key.replace("_", " ")}:*\n{pretty_lines}')
            lines.append('\n')

    if lines:
        message = f'{message}Detected after the last upload flow: commit: {commit}\n' + '\n'.join(lines)
    else:
        message = f"{message}:white_check_mark: `content` - source code is compatible with the files in the bucket"

    return CommandResults(
        outputs_prefix='slack_msg',
        outputs_key_field='',
        outputs={'msg': message}
    )


def options_handler():
    """Validates and parses script arguments.

    Returns:
        Namespace: Parsed arguments object.

    """
    parser = argparse.ArgumentParser(description="Checks that the code uploaded to production buckets is same as the code \
        in content master branch.")
    parser.add_argument("-b", "--bucket_name", help="The bucket's name to compare the master with", required=True)
    return parser.parse_args()


def main() -> None:
    # """main function, parses params and runs the command function
    # """
    # params = demisto.params()
    # bucket_name = params.get('bucket_name')

    # service_account = params.get('service_account_json', {}).get('password')

    # storage_client = storage.Client.from_service_account_info(json.loads(service_account))
    # handle_proxy()

    # demisto.debug(f'Command being called is {demisto.command()}')
    # args = demisto.args()

    # delete_folders()
    
    install_logging("Copy_and_Upload_Packs.log", logger=logging)
    options = options_handler()

    logging.debug(f"Parsed arguments: {options}")
    
    bucket_name = options.bucket_name
    
    try:
        check_content_shipped_code(bucket_name=bucket_name)
    
    #     if demisto.command() == 'test-module':
    #         result = module_test(storage_client=storage_client, bucket_name=bucket_name)
    #         return_results(result)

    #     elif demisto.command() == 'check-content-code':
    #         command_results, file_results = check_content_shipped_code_command(storage_client=storage_client,
    #                                                                            bucket_name=bucket_name)
    #         if file_results:
    #             return_results(file_results)
    #         return_results(command_results)

    #     elif demisto.command() == 'create-slack-message':
    #         return_results(create_slack_message_command(args, bucket_name=bucket_name))

    # Log exceptions and return errors
    except Exception as e:
        demisto.error(traceback.format_exc())
        delete_folders()
        return_error(f'Failed to execute {demisto.command()} command.\nError:\n{str(e)}'
                     f'\ntraceback:\n{str(traceback.format_exc())}')


''' ENTRY POINT '''

if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
