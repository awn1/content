from http import HTTPStatus
from typing import Any, Dict

import demistomock as demisto
import urllib3
from CommonServerPython import *  # noqa # pylint: disable=unused-wildcard-import
from CommonServerUserPython import *  # noqa
from AWSApiModule import *  # noqa: E402

# Disable insecure warnings
urllib3.disable_warnings()

""" CONSTANTS """

DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"  # ISO8601 format with UTC, default in XSOAR
SERVICE = 's3'


def list_buckets_command(service: str, params: Dict[str, Any], args: Dict[str, Any], aws_client: AWSClient) -> CommandResults:
    
    target_role_arn = f"arn:aws:iam::{args.get('account_id')}:role/{params.get('target_role_name')}"
    sts_client = aws_client.aws_session(service=service,
                                        region=args.get('region'),
                                        role_session_name=demisto.integrationInstance().replace(" ", "-"),
                                        role_session_duration=params.get('main_role_session_duration'),
                                        target_role_arn=target_role_arn)
    data = []
    demisto.debug("Sending request to list bucket")
    response = sts_client.list_buckets()
    for bucket in response['Buckets']:
        data.append({'BucketName': bucket['Name'],
                    'CreationDate': datetime.strftime(bucket['CreationDate'], '%Y-%m-%dT%H:%M:%S')})
    human_readable = tableToMarkdown(f'AWS {service.title()} Buckets', data)
    return CommandResults(readable_output=human_readable, outputs_prefix=f'AWS.{service.title()}.Buckets',
                          outputs_key_field='BucketName', outputs=data)


def put_public_access_block(service: str, params: Dict[str, Any], args: Dict[str, Any], aws_client: AWSClient) -> CommandResults:
    target_role_arn = f"arn:aws:iam::{args.get('account_id')}:role/{params.get('target_role_name')}"
    client = aws_client.aws_session(service=service,
                                    region=args.get('region'),
                                    role_session_name=demisto.integrationInstance().replace(" ", "-"),
                                    role_session_duration=args.get('main_role_session_duration'),
                                    target_role_arn=target_role_arn)
    kwargs = {'Bucket': args.get('bucket'),
              'PublicAccessBlockConfiguration': {'BlockPublicAcls': argToBoolean(args.get('BlockPublicAcls')),
                                                 'IgnorePublicAcls': argToBoolean(args.get('IgnorePublicAcls')),
                                                 'BlockPublicPolicy': argToBoolean(args.get('BlockPublicPolicy')),
                                                 'RestrictPublicBuckets': argToBoolean(
                                                     args.get('RestrictPublicBuckets'))}}
    response = client.put_public_access_block(**kwargs)

    if response['ResponseMetadata']['HTTPStatusCode'] == HTTPStatus.OK:
        return CommandResults(
            readable_output=f"Successfully applied public access block to the {args.get('bucket')} bucket")
    return CommandResults(readable_output=f"Couldn't apply public access block to the {args.get('bucket')} bucket")


def get_command_service_name(command: str) -> str:
    return command.split("-")[1]


def main():  # pragma: no cover
    params = demisto.params()
    aws_default_region = params.get('default_region')
    aws_role_arn = params.get('main_role_arn')
    aws_role_session_name = params.get('main_role_session_name')
    aws_role_session_duration = params.get('main_role_session_duration')
    aws_role_policy = None
    aws_access_key_id = None
    aws_secret_access_key = None
    verify_certificate = not params.get('insecure', True)
    timeout = params.get('timeout')
    retries = params.get('retries') or 5
    sts_endpoint_url = params.get('sts_endpoint_url') or None
    endpoint_url = params.get('endpoint_url') or None

    try:
        command = demisto.command()
        # validate_params(aws_default_region, aws_role_arn, aws_role_session_name, aws_access_key_id,
        #                 aws_secret_access_key)

        aws_client = AWSClient(aws_default_region, aws_role_arn, aws_role_session_name, aws_role_session_duration,
                               aws_role_policy, aws_access_key_id, aws_secret_access_key, verify_certificate, timeout,
                               retries, sts_endpoint_url=sts_endpoint_url, endpoint_url=endpoint_url)

        args = demisto.args()

        demisto.info(f'Command being called is {demisto.command()}')
        if command == 'test-module':
            aws_client.aws_session(service=SERVICE)
            demisto.results('ok')

        elif command.endswith("-list-buckets"):
            return_results(list_buckets_command(get_command_service_name(command), params, args, aws_client))

        elif command.endswith("-put-public-access-block"):
            return_results(put_public_access_block(get_command_service_name(command), params, args, aws_client))

        else:
            raise NotImplementedError(f'{command} command is not implemented.')

    except Exception as e:
        return_error(f'Failed to execute {command} command.\nError:\n{str(e)}')


if __name__ in ('__builtin__', 'builtins', '__main__'):
    main()
