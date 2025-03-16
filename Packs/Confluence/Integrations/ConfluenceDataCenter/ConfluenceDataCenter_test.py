import json
from io import BytesIO

import pytest
import requests
from requests import Session

import demistomock as demisto
from CommonServerPython import DemistoException
from ConfluenceDataCenter import Client, confluence_dc_list_spaces_command, confluence_dc_get_space_content_command, confluence_dc_get_page_command, fetch_incidents

def dict_to_response(data, status=200):
    response = requests.Response()
    response.status_code = status
    response.raw = BytesIO(json.dumps(data).encode('utf-8'))
    response.headers['Content-Type'] = 'application/json'
    return response

def load_test_data(json_path):
    with open(json_path) as f:
        return json.load(f)

@pytest.fixture
def _mocker(mocker):
    mocker.patch.object(demisto, 'params', return_value={
        'base_url': 'https://test.atlassian.net',
        'token': 'test_token',
        'default_space': 'TEST',
        'insecure': False,
        'proxy': False
    })
    return mocker

def test_list_spaces_command(_mocker):
    """
    Given:
     - A request to list Confluence spaces

    When:
     - Running confluence_dc_list_spaces_command function

    Then:
     - Ensure the function runs as expected and returns formatted results
    """
    from ConfluenceDataCenter import Client, confluence_dc_list_spaces_command

    mock_response = load_test_data('./test_data/list_spaces_response.json')
    _mocker.patch.object(Session, 'get', return_value=dict_to_response(mock_response))

    client = Client('https://test.atlassian.net', False, {})
    result = confluence_dc_list_spaces_command(client, {'limit': 25})

    assert result.outputs_prefix == 'ConfluenceDC.Space'
    assert result.outputs_key_field == 'Key'
    assert len(result.outputs) == 2
    assert result.outputs[0]['Key'] == 'TEST'
    assert result.outputs[1]['Name'] == 'Development'

def test_get_space_content_command(_mocker):
    """
    Given:
     - A request to get content from a Confluence space

    When:
     - Running confluence_dc_get_space_content_command function

    Then:
     - Ensure the function runs as expected and returns formatted results
    """
    from ConfluenceDataCenter import Client, confluence_dc_get_space_content_command

    mock_response = load_test_data('./test_data/get_space_content_response.json')
    _mocker.patch.object(Session, 'get', return_value=dict_to_response(mock_response))

    client = Client('https://test.atlassian.net', False, {})
    result = confluence_dc_get_space_content_command(client, {'space_key': 'TEST', 'limit': 25})

    assert result.outputs_prefix == 'ConfluenceDC.Content'
    assert result.outputs_key_field == 'ID'
    assert len(result.outputs) == 2
    assert result.outputs[0]['Title'] == 'Test Page'
    assert result.outputs[1]['SpaceKey'] == 'TEST'

def test_get_page_command(_mocker):
    """
    Given:
     - A request to get a specific Confluence page

    When:
     - Running confluence_dc_get_page_command function

    Then:
     - Ensure the function runs as expected and returns formatted results
    """
    from ConfluenceDataCenter import Client, confluence_dc_get_page_command

    mock_response = load_test_data('./test_data/get_page_response.json')
    _mocker.patch.object(Session, 'get', return_value=dict_to_response(mock_response))

    client = Client('https://test.atlassian.net', False, {})
    result = confluence_dc_get_page_command(client, {'page_id': '123', 'expand': 'body'})

    assert result.outputs_prefix == 'ConfluenceDC.Page'
    assert result.outputs_key_field == 'ID'
    assert result.outputs['Title'] == 'Test Page'
    assert result.outputs['Version'] == 5
    assert '<p>Test content</p>' in result.outputs['Body']

def test_fetch_incidents(_mocker):
    """
    Given:
     - A request to fetch incidents (new pages) from Confluence

    When:
     - Running fetch_incidents function

    Then:
     - Ensure the function runs as expected and returns new incidents
    """
    from ConfluenceDataCenter import Client, fetch_incidents

    mock_response = load_test_data('./test_data/fetch_incidents_response.json')
    _mocker.patch.object(Session, 'get', return_value=dict_to_response(mock_response))

    client = Client('https://test.atlassian.net', False, {})
    last_run = {'last_fetch': '2023-04-30T00:00:00Z'}
    next_run, incidents = fetch_incidents(client, last_run, '3 days', 'TEST')

    assert next_run['last_fetch'] == '2023-05-02T11:00:00Z'
    assert len(incidents) == 2
    assert incidents[0]['name'] == 'New Confluence Page: New Page'
    assert incidents[1]['name'] == 'New Confluence Page: Another New Page'

def test_get_modified_remote_data_command(_mocker):
    """
    Given:
     - A request to get modified remote data for mirroring

    When:
     - Running get_modified_remote_data_command function

    Then:
     - Ensure the function runs as expected and returns modified page IDs
    """
    from ConfluenceDataCenter import Client, get_modified_remote_data_command

    mock_spaces_response = load_test_data('./test_data/list_spaces_response.json')
    mock_content_response = load_test_data('./test_data/get_modified_content_response.json')
    
    _mocker.patch.object(Session, 'get', side_effect=[
        dict_to_response(mock_spaces_response),
        dict_to_response(mock_content_response)
    ])

    client = Client('https://test.atlassian.net', False, {})
    args = {'lastUpdate': '2023-05-01T00:00:00Z'}
    result = get_modified_remote_data_command(client, args)

    assert isinstance(result, GetModifiedRemoteDataResponse)
    assert len(result.modified_incident_ids) == 1
    assert result.modified_incident_ids[0] == '456'

def test_get_remote_data_command(_mocker):
    """
    Given:
     - A request to get remote data for a specific page

    When:
     - Running get_remote_data_command function

    Then:
     - Ensure the function runs as expected and returns page data and comments
    """
    from ConfluenceDataCenter import Client, get_remote_data_command

    mock_page_response = load_test_data('./test_data/get_page_with_comments_response.json')
    _mocker.patch.object(Session, 'get', return_value=dict_to_response(mock_page_response))

    client = Client('https://test.atlassian.net', False, {})
    args = {'id': '123', 'lastUpdate': '2023-05-01T00:00:00Z'}
    result = get_remote_data_command(client, args)

    assert isinstance(result, GetRemoteDataResponse)
    assert result.mirrored_object['Title'] == 'Test Page'
    assert len(result.entries) == 2
    assert result.entries[0]['Type'] == EntryType.NOTE
    assert 'Test comment' in result.entries[0]['Contents']

