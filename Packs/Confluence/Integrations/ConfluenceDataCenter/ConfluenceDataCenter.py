
import urllib3
from typing import Any, Dict, List, Optional

import demistomock as demisto
from CommonServerPython import *
from CommonServerUserPython import *
from datetime import datetime, timedelta

# Disable insecure warnings
urllib3.disable_warnings()

DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"  # ISO8601 format with UTC, default in XSOAR
SPACES_ENDPOINT = '/space'
CONTENT_ENDPOINT = '/content'



class Client(BaseClient):
    """Client class to interact with the service API

    This Client implements API calls, and does not contain any XSOAR logic.
    Should only do requests and return data.
    It inherits from BaseClient defined in CommonServer Python.
    Most calls use _http_request() that handles proxy, SSL verification, etc.
    For this  implementation, no special attributes defined
    """

    def list_spaces(self, limit: int = 25) -> Dict[str, Any]:
        return self._http_request(
            method='GET',
            url_suffix=SPACES_ENDPOINT,
            params={'limit': limit}
        )

    def get_space_content(self, space_key: str, content_type: Optional[str] = None, limit: int = 25) -> Dict[str, Any]:
        params = {'spaceKey': space_key, 'limit': limit}
        if content_type:
            params['type'] = content_type
        return self._http_request(
            method='GET',
            url_suffix=CONTENT_ENDPOINT,
            params=params
        )

    def get_page(self, page_id: str, expand: Optional[str] = None) -> Dict[str, Any]:
        params = {}
        if expand:
            params['expand'] = expand
        return self._http_request(
            method='GET',
            url_suffix=f'{CONTENT_ENDPOINT}/{page_id}',
            params=params
        )


def test_module(client: Client) -> str:
    """Tests API connectivity and authentication'

    Returning 'ok' indicates that the integration works like it is supposed to.
    Connection to the service is successful.
    Raises:
     exceptions if something goes wrong.

    Args:
        Client: client to use

    Returns:
        'ok' if test passed, anything else will fail the test.
    """

    client.list_spaces(limit=1)
    return 'ok'


def confluence_dc_list_spaces_command(client: Client, args: Dict[str, Any]) -> CommandResults:
    limit = arg_to_number(args.get('limit', 25))
    raw_response = client.list_spaces(limit)
    spaces = raw_response.get('results', [])

    outputs = []
    for space in spaces:
        outputs.append({
            'Key': space.get('key'),
            'Name': space.get('name'),
            'Type': space.get('type')
        })

    return CommandResults(
        outputs_prefix='ConfluenceDC.Space',
        outputs_key_field='Key',
        outputs=outputs,
        raw_response=raw_response
    )

def confluence_dc_get_space_content_command(client: Client, args: Dict[str, Any]) -> CommandResults:
    space_key = args['space_key']
    content_type = args.get('content_type')
    limit = arg_to_number(args.get('limit', 25))

    raw_response = client.get_space_content(space_key, content_type, limit)
    content_items = raw_response.get('results', [])

    outputs = []
    for item in content_items:
        outputs.append({
            'ID': item.get('id'),
            'Title': item.get('title'),
            'Type': item.get('type'),
            'SpaceKey': item.get('space', {}).get('key')
        })

    return CommandResults(
        outputs_prefix='ConfluenceDC.Content',
        outputs_key_field='ID',
        outputs=outputs,
        raw_response=raw_response
    )

def confluence_dc_get_page_command(client: Client, args: Dict[str, Any]) -> CommandResults:
    page_id = args['page_id']
    expand = args.get('expand')

    raw_response = client.get_page(page_id, expand)

    output = {
        'ID': raw_response.get('id'),
        'Title': raw_response.get('title'),
        'Version': raw_response.get('version', {}).get('number'),
        'SpaceKey': raw_response.get('space', {}).get('key'),
    }

    if expand and 'body' in expand:
        output['Body'] = raw_response.get('body', {}).get('storage', {}).get('value')

    return CommandResults(
        outputs_prefix='ConfluenceDC.Page',
        outputs_key_field='ID',
        outputs=output,
        raw_response=raw_response
    )


def fetch_incidents(client: Client, last_run: Dict[str, Any], first_fetch_time: str, default_space: str):
    last_fetch = last_run.get('last_fetch', first_fetch_time)
    latest_created_time = last_fetch
    incidents = []

    # Fetch new pages from the default space
    response = client.get_space_content(default_space, content_type='page', limit=50)
    pages = response.get('results', [])

    for page in pages:
        created_date = page.get('created')
        if created_date > last_fetch:
            incident = {
                'name': f"New Confluence Page: {page.get('title')}",
                'occurred': created_date,
                'rawJSON': json.dumps(page)
            }
            incidents.append(incident)
            latest_created_time = max(latest_created_time, created_date)

    next_run = {'last_fetch': latest_created_time}
    return next_run, incidents


def get_modified_remote_data_command(client: Client, args: dict) -> GetModifiedRemoteDataResponse:
    remote_args = GetModifiedRemoteDataArgs(args)
    last_update = validate_iso_time_format(remote_args.last_update)
    demisto.debug(f"get-modified-remote-data command {last_update=}")

    spaces = client.list_spaces()
    modified_pages = []
    for space in spaces.get('results', []):
        space_key = space.get('key')
        pages = client.get_space_content(space_key, content_type='page')
        for page in pages.get('results', []):
            if page.get('lastModified') > last_update:
                modified_pages.append(str(page.get('id')))

    demisto.debug(f"get-modified-remote-data command {modified_pages=}")
    return GetModifiedRemoteDataResponse(modified_pages)

def get_remote_data_command(client: Client, args: dict) -> GetRemoteDataResponse:
    remote_args = GetRemoteDataArgs(args)
    page_id = remote_args.remote_incident_id
    demisto.debug(f"get_remote_data_command {page_id=}")

    page = client.get_page(page_id, expand='body,version,space')
    
    mirrored_object = {
        'ID': page.get('id'),
        'Title': page.get('title'),
        'Version': page.get('version', {}).get('number'),
        'SpaceKey': page.get('space', {}).get('key'),
        'Body': page.get('body', {}).get('storage', {}).get('value'),
    }

    entries = []
    if comments := page.get('comments', {}).get('results', []):
        for comment in comments:
            entries.append({
                'Type': EntryType.NOTE,
                'Contents': comment.get('content'),
                'ContentsFormat': EntryFormat.TEXT,
            })

    demisto.debug(f"get_remote_data_command mirrored_object={mirrored_object}")
    return GetRemoteDataResponse(mirrored_object=mirrored_object, entries=entries)

def main():
    params = demisto.params()
    base_url = urljoin(params['base_url'], '/rest/api')
    verify_certificate = not params.get('insecure', False)
    proxy = params.get('proxy', False)

    token = params['token']
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    
    client = Client(
        base_url=base_url,
        verify=verify_certificate,
        headers=headers,
        proxy=proxy,
    )

    command = demisto.command()
    demisto.debug(f'Command being called is {command}')
    # Configure mirroring
    mirror_direction = params.get('mirror_direction', 'None')

    # Fetch incidents parameters
    default_space = params.get('default_space')
    first_fetch_time = params.get('first_fetch', '3 days').strip()
    first_fetch_timestamp = parse_date_range(first_fetch_time)[0]

    try:
        if command == 'test-module':
            return_results(test_module(client))
        elif command == 'fetch-incidents':
            next_run, incidents = fetch_incidents(
                client,
                demisto.getLastRun(),
                first_fetch_timestamp,
                default_space
            )
            demisto.setLastRun(next_run)
            demisto.incidents(incidents)
        elif command == 'confluence-dc-list-spaces':
            return_results(confluence_dc_list_spaces_command(client, demisto.args()))
        elif command == 'confluence-dc-get-space-content':
            return_results(confluence_dc_get_space_content_command(client, demisto.args()))
        elif command == 'confluence-dc-get-page':
            return_results(confluence_dc_get_page_command(client, demisto.args()))
        elif command == 'get-modified-remote-data':
            return_results(get_modified_remote_data_command(client, demisto.args()))
        elif command == 'get-remote-data':
            return_results(get_remote_data_command(client, demisto.args()))
        else:
            raise NotImplementedError(f'{command} is not an existing Confluence Data Center command')
    except Exception as e:
        return_error(f'Failed to execute {command} command.\nError:\n{str(e)}')
if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
