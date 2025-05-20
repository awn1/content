from typing import Any

import urllib3

import demistomock as demisto
from CommonServerPython import *  # noqa # pylint: disable=unused-wildcard-import
from CommonServerUserPython import *  # noqa

# Disable insecure warnings
urllib3.disable_warnings()  # pylint: disable=no-member
import aiohttp
import asyncio
from itertools import chain
''' CONSTANTS '''

ALL_SUPPORTED_EVENT_TYPES = ['application', 'alert', 'page', 'audit', 'network', 'incident']
MAX_EVENTS_PAGE_SIZE = 10000
MAX_SKIP = 50000
EXECUTION_TIMEOUT_SECONDS = 190  # 3:30 minutes

# Netskope response constants
WAIT_TIME = 'wait_time'  # Wait time between queries
RATE_LIMIT_REMAINING = "ratelimit-remaining"  # Rate limit remaining
RATE_LIMIT_RESET = "ratelimit-reset"  # Rate limit RESET value is in seconds
POC = True
''' CLIENT CLASS '''


class Client(BaseClient):
    """
    Client for Netskope RESTful API.

    Args:
        base_url (str): The base URL of Netskope.
        token (str): The token to authenticate against Netskope API.
        validate_certificate (bool): Specifies whether to verify the SSL certificate or not.
        proxy (bool): Specifies if to use XSOAR proxy settings.
    """

    def __init__(self, base_url: str, token: str, validate_certificate: bool, proxy: bool, event_types_to_fetch: list[str]):
        self.fetch_status: dict = {event_type: False for event_type in event_types_to_fetch}
        self.event_types_to_fetch: list[str] = event_types_to_fetch
        self.netskope_semaphore = asyncio.Semaphore(3)
        headers = {"Netskope-Api-Token": f"{token}", "Accept": "application/json"}
        super().__init__(base_url, verify=validate_certificate, proxy=proxy, headers=headers)

    def perform_data_export(self, endpoint: str, _type: str, index_name: str, operation: str):
        url_suffix = f"events/dataexport/{endpoint}/{_type}"
        params = {"index": index_name, "operation": operation}
        response = self._http_request(method="GET", url_suffix=url_suffix, params=params, resp_type="response", retries=10)
        honor_rate_limiting(headers=response.headers, endpoint=url_suffix)
        return response.json()

    def poc_fetch_events(self, type: str, params: dict):
        url_suffix = f"events/data/{type}"
        response = self._http_request(method="GET", url_suffix=url_suffix, params=params, resp_type="response", retries=10)
        # honor_rate_limiting(headers=response.headers, endpoint=url_suffix)
        return response.json()
    
    def fetch_events_async_to_remove_it(self, type: str, params: dict, limit: int):
        url_suffix = f"events/data/{type}"
        url = urljoin(self._base_url, url_suffix)
        
        async def _get_events_count(session: aiohttp.ClientSession):
            async with session.get(url, params=params | {'fields': 'event_count:count(id)'}, headers=self._headers) as resp:
                res = await resp.json()
                event_count = res.get('result', [{}])[0].get('event_count')
                demisto.debug(f'there is {event_count} total {type} events for the given time')
                return event_count
        
        
        async def _handle_page(session, params, netskope_sem, xsiam_sem):
            async def _fetch_page(session: aiohttp.ClientSession, params, sem):
                async with sem:
                    async with session.get(url, params=params, headers=self._headers) as resp:
                        return await resp.json()
            async def _send_page_to_xsiam(res, xsiam_sem):
                async with xsiam_sem:
                    offset = params.get('offset')
                    demisto.debug(f"send {offset=}, {len(res.get('result', []))} events to xsiam")
                    await asyncio.sleep(1)
            res = await _fetch_page(session, params, netskope_sem)
            await _send_page_to_xsiam(res, xsiam_sem)
            return res

        async def handle_all_pages(limit):
            netskope_sem = asyncio.Semaphore(4)
            xsiam_sem = asyncio.Semaphore(20)
            async with aiohttp.ClientSession() as session:
                total_events =  await _get_events_count(session)
                tasks = [
                    _handle_page(session, params | {'offset': offset}, netskope_sem, xsiam_sem)
                    for offset in range(0, total_events, limit)
                ]

                results = await asyncio.gather(*tasks)
            return results

        async def _fetch_and_send():
            results = await handle_all_pages(limit)
            return list(chain.from_iterable([r.get('result', []) for r in results]))
        
        all_events = asyncio.run(_fetch_and_send())        
        
        # honor_rate_limiting(headers=response.headers, endpoint=url_suffix)
        return {'result': all_events}

    async def get_events_data_async(self, type, params, session: aiohttp.ClientSession):
        url_suffix = f"events/data/{type}"
        url = urljoin(self._base_url, url_suffix)
        async with self.netskope_semaphore:
            async with session.get(url, params=params, headers=self._headers) as resp:
                demisto.debug(f'getting {type} events data, {params=}')
                resp.raise_for_status()
                return await resp.json()
    
    async def get_events_count(self, type, params, session: aiohttp.ClientSession):
        """Return the count of event existing for the given type and time

        Args:
            type (str): the events type
            params (dict): request params
            session (aiohttp.ClientSession): the session
            sem (asyncio.Semaphore): a semaphore

        Returns:
            str: the count of event existing for the given type and time
        """
        res = await self.get_events_data_async(type, params | {'fields': 'event_count:count(id)'}, session)
        event_count = res.get('result', [{}])[0].get('event_count')
        demisto.debug(f'there is {event_count} total {type} events for the given time')
        return event_count

''' HELPER FUNCTIONS '''


def honor_rate_limiting(headers, endpoint):
    """
    Identify the response headers carrying the rate limiting value.
    If the rate limit remaining for this endpoint is 0 then wait for the rate limit reset time before sending the response to the
    client.
    """
    try:
        if RATE_LIMIT_REMAINING in headers:
            remaining = headers.get(RATE_LIMIT_REMAINING)
            demisto.debug(f'Remaining rate limit is: {remaining}')
            if int(remaining) <= 0:
                demisto.debug(f'Rate limiting reached for the endpoint: {endpoint}')
                if to_sleep := headers.get(RATE_LIMIT_RESET):
                    demisto.debug(f'Going to sleep for {to_sleep} seconds to avoid rate limit error')
                    time.sleep(int(to_sleep))
                else:
                    # if the RESET value does not exist in the header then
                    # sleep for default 1 second as the rate limit remaining is 0
                    demisto.debug('Did not find a rate limit reset value, going to sleep for 1 second to avoid rate limit error')
                    time.sleep(1)

    except ValueError as ve:
        logging.error(f"Value error when honoring the rate limiting wait time {headers} {str(ve)}")


def populate_parsing_rule_fields(event: dict, event_type: str):
    """
    Handles the source_log_event and _time fields.
    Sets the source_log_event to the given event type and _time to the time taken from the timestamp field

    Args:
        event (dict): the event to edit
        event_type (str): the event type tp set in the source_log_event field
    """
    event['source_log_event'] = event_type
    try:
        event['_time'] = timestamp_to_datestring(event['timestamp'] * 1000, is_utc=True)
    except TypeError:
        # modeling rule will default on ingestion time if _time is missing
        pass


def prepare_events(events: list, event_type: str) -> list:
    """
    Iterates over a list of given events and add/modify special fields like event_id, _time and source_log_event.

    Args:
        events (list): list of events to modify.
        event_type (str): the type of events given in the list.

    Returns:
        list: the list of modified events
    """
    for event in events:
        populate_parsing_rule_fields(event, event_type)
        event_id = event.get('_id')
        event['event_id'] = event_id

    return events


def poc_prepare_events_old(events: list, event_type: str, last_run: dict, epoch_starttime: str) -> list[Any]:
    """
    - Iterates over a list of given events and add/modify special fields like event_id, _time and source_log_event.
    - sort results by _creation_timestamp key
    - dedup with IDs from previous fetch, if available
    - get max epoch from fetch events

    Args:
        events (list): list of events to modify.
        event_type (str): the type of events given in the list.

    Returns:
        list: the list of modified events
    """
    last_fetch_ids = set(last_run.get(event_type, {}).get("last_fetch_ids", []))

    deduped_events = []
    max_epoch = epoch_starttime

    for event in events:
        if (event_id := str(event.get("_id"))) not in last_fetch_ids:
            populate_parsing_rule_fields(event, event_type)
            event["event_id"] = event_id
            deduped_events.append(event)
            max_epoch = max(max_epoch, str(event.get("_creation_timestamp", "")))

    last_run.setdefault(event_type, {})
    last_run[event_type]["last_fetch_ids"] = [event["event_id"] for event in deduped_events]
    last_run[event_type]["last_fetch_max_epoch"] = max_epoch

    return deduped_events


def poc_prepare_events(events: list, event_type: str) -> list[Any]:
    """
    - Iterates over a list of given events and add/modify special fields like event_id, _time and source_log_event.

    Args:
        events (list): list of events to modify.
        event_type (str): the type of events given in the list.

    Returns:
        list: the list of modified events
    """

    for event in events:
        populate_parsing_rule_fields(event, event_type)
        event["event_id"] = str(event.get("_id"))

    return deduped_events


def print_event_statistics_logs(events: list, event_type: str):
    """
    Helper function for debugging purposes.
    This function is responsible to print statistics about pulled events, like the amount of pulled events and the first event and
    last event times.

    Args:
        events (list): list of events.
        event_type (str): the type of events given in the list.
    """
    demisto.debug(f'__[{event_type}]__ - Total events fetched this round: {len(events)}')
    if events:
        event_times = f'__[{event_type}]__ - First event: {events[0].get("timestamp")} __[{event_type}]__ - Last event: ' \
                      f'{events[-1].get("timestamp")}'
        demisto.debug(event_times)


def is_execution_time_exceeded(start_time: datetime) -> bool:
    """
    Checks if the execution time so far exceeded the timeout limit.

    Args:
        start_time (datetime): the time when the execution started.

    Returns:
        bool: true, if execution passed timeout settings, false otherwise.
    """
    end_time = datetime.utcnow()
    secs_from_beginning = (end_time - start_time).seconds
    demisto.debug(f'Execution length so far is {secs_from_beginning} secs')

    return secs_from_beginning > EXECUTION_TIMEOUT_SECONDS


def remove_unsupported_event_types(last_run_dict: dict, event_types_to_fetch: list):
    keys_to_remove = []

    for key in last_run_dict:
        if (key in ALL_SUPPORTED_EVENT_TYPES) and (key not in event_types_to_fetch):
            keys_to_remove.append(key)

    for key in keys_to_remove:
        last_run_dict.pop(key, None)


def setup_last_run(last_run_dict: dict, event_types_to_fetch: list[str]) -> dict:
    """
    Setting the last_tun object with the right operation to be used throughout the integration run.

    Args:
        last_run_dict (dict): The dictionary of the last run to be configured

    Returns:
        dict: the modified last run dictionary with the needed operation
    """
    remove_unsupported_event_types(last_run_dict, event_types_to_fetch)
    first_fetch = int(arg_to_datetime('now').timestamp())  # type: ignore[union-attr]
    for event_type in event_types_to_fetch:
        if not last_run_dict.get(event_type, {}).get('operation'):
            last_run_dict[event_type] = {'operation': first_fetch}

    demisto.debug(f'Initialize last run to - {last_run_dict}')

    return last_run_dict


def handle_data_export_single_event_type(client: Client, event_type: str, operation: str, limit: int,
                                         execution_start_time: datetime, all_event_types: list) -> bool:
    """
    Pulls events per each given event type. Each event type receives a dedicated index name that is constructed using the event
    type and the integration instance name. The function keeps pulling events as long as the limit was not exceeded.
    - First thing it validates is that execution time of the entire run was not exceeded.
    - Then it checks if we need to wait some time before making another call to the same endpoint by checking the wait_time value
        received in the previous response.
    - The operation variable marks the next operation to perform on this endpoint (besides the first fetch it is always 'next')
    - After it is done pulling, it marks this event type as successfully done in the 'fetch_status' dictionary.

    Args:
        client (Client): The Netskope client.
        event_type (str): The type of event to pull.
        operation (str): The operation to perform. Can be 'next' or a timestamp string.
        limit (int): The limit which after we stop pulling.
        execution_start_time (datetime): The time when we started running the fetch mechanism.

    Return:
        list: The list of events pulled for the given event type.
        bool: Was execution timeout reached.
    """
    wait_time: int = 0
    events: list[dict] = []
    # We use the instance name to allow multiple instances in parallel without causing a collision in index names
    instance_name = demisto.callingContext.get('context', {}).get('IntegrationInstance')
    index_name = f'xsoar_collector_{instance_name}_{event_type}'

    while len(events) < limit:

        # If the execution exceeded the timeout we will break
        if is_execution_time_exceeded(start_time=execution_start_time):
            return True

        # Wait time between queries
        if wait_time:
            demisto.debug(f'Going to sleep between queries, wait_time is {wait_time} seconds')
            time.sleep(wait_time)  # pylint: disable=E9003
        else:
            demisto.debug('No wait time received, going to sleep for 1 second')
            time.sleep(1)

        response = client.perform_data_export('events', event_type, index_name, operation)

        results = response.get('result', [])
        demisto.debug(f'The number of received events - {len(results)}')
        operation = 'next'

        # The API responds with the time we should wait between requests, the server needs this time to prepare the next response.
        # It will be used to sleep in the beginning of the next iteration
        wait_time = arg_to_number(response.get(WAIT_TIME, 5)) or 5
        demisto.debug(f'Wait time is {wait_time} seconds')

        events.extend(results)

        all_event_types.extend(prepare_events(results, event_type))

        if not results or len(results) < MAX_EVENTS_PAGE_SIZE:
            break

    print_event_statistics_logs(events=events, event_type=event_type)
    # We mark this event type as successfully fetched
    client.fetch_status[event_type] = True
    return False


def get_all_events(client: Client, last_run: dict, all_event_types: list, limit: int = MAX_EVENTS_PAGE_SIZE) -> dict:
    """
    Iterates over all supported event types and call the handle data export logic. Once each event type is done the operation for
    next run is set to 'next'.

    Args:
        client (Client): The Netskope client.
        last_run (dict): The execution last run dict where the relevant operations are stored.
        limit (int): The limit which after we stop pulling.

    Returns:
        list: The accumulated list of all events.
        dict: The updated last_run object.
    """

    execution_start_time = datetime.utcnow()
    for event_type in client.event_types_to_fetch:
        event_type_operation = last_run.get(event_type, {}).get('operation')

        time_out = handle_data_export_single_event_type(client=client, event_type=event_type,
                                                        operation=event_type_operation, limit=limit,
                                                        execution_start_time=execution_start_time,
                                                        all_event_types=all_event_types)
        last_run[event_type] = {'operation': 'next'}

        if time_out:
            demisto.info('Timeout reached, stopped pulling events')
            break

    return last_run


def poc_get_all_events(client: Client, last_run: dict, all_event_types: list, limit: int = MAX_EVENTS_PAGE_SIZE) -> dict:
    """
    Iterates over all supported event types and call the handle event fetch logic.

    Endpoint: /api/v2/events/data/
    Docs: https://www.postman.com/netskope-tech-alliances/netskope-rest-api/request/zknja6y/get-network-events-generated-by-netskope

    Example HTTP request:
    <baseUrl>/api/v2/events/data/network?offset=0&starttime=1707466628&endtime=1739089028&query=_creation_timestamp gte 1739058516

    Args:
        client (Client): The Netskope client.
        last_run (dict): The execution last run dict where the relevant operations are stored.
        limit (int): The limit which after we stop pulling.

    Returns:
        list: The accumulated list of all events.
        dict: The updated last_run object.
    """
    remove_unsupported_event_types(last_run, client.event_types_to_fetch)
    epoch_current_time = str(int(arg_to_datetime("now").timestamp()))  # type: ignore[union-attr]
    request_limit = limit if limit < MAX_EVENTS_PAGE_SIZE else MAX_EVENTS_PAGE_SIZE

    demisto.debug(f"Starting event fetch with current time: {epoch_current_time}, request limit: {request_limit}")

    for event_type in client.event_types_to_fetch:
        events = []
        demisto.debug(f"Fetching event type: {event_type}")

        while len(events) < limit:
            epoch_starttime = last_run.get(event_type, {}).get("last_fetch_max_epoch", "") or str(
                int(arg_to_datetime("2 month").timestamp())  # type: ignore[union-attr]
            )
            if epoch_starttime > epoch_current_time:
                # if last_fetch_max_epoch is higher than current time, break the loop
                demisto.debug(
                    f"Last fetched timestamp is higher than current time, breaking the loop for event type: {event_type}"
                )
                break

            query = f"_creation_timestamp gte {epoch_starttime}"  # TODO: add some sorting by '_creation_timestamp' key
            # params = assign_params(limit=request_limit, offset=0, starttime=epoch_starttime, endtime=epoch_current_time) # with out query parameter
            params = assign_params(
                limit=request_limit, offset=0, starttime=epoch_starttime, endtime=epoch_current_time, query=query
            )

            demisto.debug(f"Fetching events with params: {params}")

            response = client.poc_fetch_events(event_type, params)
            result = response.get("result", [])
            demisto.debug(f"The number of fetched events - {len(result)}")

            deduped_events = prepare_events(result, event_type)
            events.extend(deduped_events)

            demisto.debug(
                f"Deduped events: {len(deduped_events)} out of {len(result)} fetched events in current fetch cycle. Total events fetched so far: {len(events)}"
            )

            if (not result) or (not deduped_events):
                demisto.debug(
                    f"No new events fetched, finishing current fetch cycle for {event_type} event type with total of - {len(events)} new events"
                )
                break

            all_event_types.extend(deduped_events)

    demisto.debug(f"Finished fetching all event types. Total events fetched: {len(all_event_types)}")

    return last_run


def fetch_and_send_events_async(client: Client, type: str, request_params: dict, limit: int):
    support_multithreading()
    
    async def _handle_page(session, params, xsiam_sem):
        
        async def _fetch_page(session: aiohttp.ClientSession):
            offset = params.get('offset')    
            demisto.debug(f"fetching from {offset=} from netskope")
            return await client.get_events_data_async(type, params, session)

        async def _send_page_to_xsiam(events):
            async with xsiam_sem:
                demisto.debug(f"send {len(events)} events to xsiam")
                await asyncio.to_thread(
                    send_events_to_xsiam,
                    events=events, vendor='netskope',
                    product='netskope',
                    chunk_size=XSIAM_EVENT_CHUNK_SIZE_LIMIT
                )
        
        res = await _fetch_page(session)
        events = res.get('result', [])
        events = prepare_events(events, type)
        await _send_page_to_xsiam(events)
        return res

    async def _handle_all_pages():
        xsiam_sem = asyncio.Semaphore(20)
        
        async with aiohttp.ClientSession() as session:
            
            total_events =  await client.get_events_count(type, request_params, session)
            total_events = min(total_events, limit)
            
            request_limit = request_params.get('limit', MAX_EVENTS_PAGE_SIZE)
            demisto.debug(f"Going to fetch {total_events} events by chunks of {request_limit} ...")
            tasks = [
                _handle_page(session, request_params | {'offset': offset}, xsiam_sem)
                for offset in range(0, total_events, request_limit)
            ]

            results = await asyncio.gather(*tasks)
        return results
    
    results = asyncio.run(_handle_all_pages())
    events = list(chain.from_iterable([r.get('result', []) for r in results]))
    
    demisto.debug(f"The number of fetched events - {len(events)}")
    # honor_rate_limiting(headers=response.headers, endpoint=url_suffix)
    return {'result': events}


def get_all_events_async(client: Client, last_run: dict, all_event_types: list, limit: int = MAX_EVENTS_PAGE_SIZE) -> dict:
    """
    Iterates over all supported event types and call the handle event fetch logic.

    Endpoint: /api/v2/events/data/
    Docs: https://www.postman.com/netskope-tech-alliances/netskope-rest-api/request/zknja6y/get-network-events-generated-by-netskope

    Example HTTP request:
    <baseUrl>/api/v2/events/data/network?offset=0&starttime=1707466628&endtime=1739089028&query=_creation_timestamp gte 1739058516

    Args:
        client (Client): The Netskope client.
        last_run (dict): The execution last run dict where the relevant operations are stored.
        limit (int): The limit which after we stop pulling.

    Returns:
        list: The accumulated list of all events.
        dict: The updated last_run object.
    """
    remove_unsupported_event_types(last_run, client.event_types_to_fetch)

    epoch_current_time = str(int(arg_to_datetime("now").timestamp()))  # type: ignore[union-attr]
    epoch_last_month = str(int(arg_to_datetime("1 month").timestamp()))  # type: ignore[union-attr]
    request_limit = limit if limit < MAX_EVENTS_PAGE_SIZE else MAX_EVENTS_PAGE_SIZE

    demisto.debug(f"Starting event fetch with current time: {epoch_current_time}, request limit: {request_limit}")

    for event_type in client.event_types_to_fetch:
        epoch_starttime = last_run.get(event_type, {}).get("last_fetch_max_epoch", epoch_last_month)
        
        if epoch_starttime > epoch_current_time:
            demisto.debug(
                f"Last fetched timestamp is higher than current time, breaking the loop for event type: {event_type}"
            )
            break

        params = assign_params(
            limit=request_limit,
            offset=0,
            insertionstarttime=epoch_starttime,
            insertionendtime=epoch_current_time
        )

        demisto.debug(f"Fetching {event_type} events with params: {params}")
        response = fetch_and_send_events_async(client, event_type, params, limit)
        result = response.get("result", [])
        demisto.debug(f"The number of fetched events - {len(result)}")

        prepared_events = prepare_events(result, event_type)

        if not result:
            demisto.debug(f"No new {event_type} events fetched")
        
        all_event_types.extend(prepared_events)

        last_run.setdefault(event_type, {})
        last_run[event_type]["last_fetch_max_epoch"] = epoch_current_time

    demisto.debug(f"Finished fetching all event types. Total events fetched: {len(all_event_types)}")

    return last_run

''' COMMAND FUNCTIONS '''


def test_module(client: Client, last_run: dict, max_fetch: int) -> str:
    poc_get_all_events(client, last_run, limit=max_fetch, all_event_types=[])
    return 'ok'


def get_events_command_async(client: Client, args: dict[str, Any], last_run: dict, events: list) -> tuple[CommandResults, list]:
    limit = arg_to_number(args.get('limit')) or MAX_EVENTS_PAGE_SIZE
    _ = get_all_events_async(client=client, last_run=last_run, limit=limit, all_event_types=events)

    for event in events:
        event['timestamp'] = timestamp_to_datestring(event['timestamp'] * 1000)

    readable_output = tableToMarkdown('Events List:', events,
                                      removeNull=True,
                                      headers=['_id', 'timestamp', 'type', 'access_method', 'app', 'traffic_type'],
                                      headerTransform=string_to_table_header)

    results = CommandResults(outputs_prefix='Netskope.Event',
                             outputs_key_field='_id',
                             outputs=events,
                             readable_output=readable_output,
                             raw_response=events)

    return results, events


def get_events_command(client: Client, args: dict[str, Any], last_run: dict, events: list) -> tuple[CommandResults, list]:
    limit = arg_to_number(args.get('limit')) or MAX_EVENTS_PAGE_SIZE
    _ = get_all_events(client=client, last_run=last_run, limit=limit, all_event_types=events)

    for event in events:
        event['timestamp'] = timestamp_to_datestring(event['timestamp'] * 1000)

    readable_output = tableToMarkdown('Events List:', events,
                                      removeNull=True,
                                      headers=['_id', 'timestamp', 'type', 'access_method', 'app', 'traffic_type'],
                                      headerTransform=string_to_table_header)

    results = CommandResults(outputs_prefix='Netskope.Event',
                             outputs_key_field='_id',
                             outputs=events,
                             readable_output=readable_output,
                             raw_response=events)

    return results, events


def handle_event_types_to_fetch(event_types_to_fetch) -> list[str]:
    """ Handle event_types_to_fetch parameter.
        Transform the event_types_to_fetch parameter into a pythonic list with lowercase values.
    """
    return argToList(
        arg=event_types_to_fetch if event_types_to_fetch else ALL_SUPPORTED_EVENT_TYPES,
        transform=lambda x: x.lower(),
    )


def next_trigger_time(num_of_events, max_fetch, new_last_run):
    """Check wether to add the next trigger key to the next_run dict based on number of fetched events.

    Args:
        num_of_events (int): The number of events fetched.
        max_fetch (int): The maximum fetch limit.
        new_last_run (dict): the next_run to update
    """
    if num_of_events > (max_fetch / 2):
        new_last_run['nextTrigger'] = '0'
    else:
        new_last_run.pop('nextTrigger', None)


''' MAIN FUNCTION '''


def main() -> None:  # pragma: no cover
    try:
        params = demisto.params()

        url = params.get('url')
        token = params.get('credentials', {}).get('password')
        base_url = urljoin(url, '/api/v2/')
        verify_certificate = not params.get('insecure', False)
        proxy = params.get('proxy', False)
        max_fetch: int = arg_to_number(params.get('max_fetch')) or 10000
        vendor, product = params.get('vendor', 'netskope'), params.get('product', 'netskope')
        event_types_to_fetch = handle_event_types_to_fetch(params.get('event_types_to_fetch'))
        demisto.debug(f'Event types that will be fetched in this instance: {event_types_to_fetch}')
        command_name = demisto.command()
        demisto.debug(f'Command being called is {command_name}')

        client = Client(base_url, token, verify_certificate, proxy, event_types_to_fetch)

        if POC:
            last_run = demisto.getLastRun()
        else:
            last_run = setup_last_run(demisto.getLastRun(), event_types_to_fetch)
        demisto.debug(f'Running with the following last_run - {last_run}')

        all_event_types: list[dict] = []
        new_last_run: dict = {}
        if command_name == 'test-module':
            # This is the call made when pressing the integration Test button.
            result = test_module(client, last_run, max_fetch=MAX_EVENTS_PAGE_SIZE)  # type: ignore[arg-type]
            return_results(result)

        elif command_name == 'netskope-get-events':
            results, events = get_events_command(client, demisto.args(), last_run, events=[])
            if argToBoolean(demisto.args().get('should_push_events', 'true')):
                demisto.debug("send_all_events_to_xsiam disabled in the POC integration")
                # send_events_to_xsiam(events=events, vendor=vendor, product=product,
                #  chunk_size=XSIAM_EVENT_CHUNK_SIZE_LIMIT)  # type: ignore
            return_results(results)

        elif command_name == 'fetch-events':
            if POC:
                start = datetime.utcnow()
                
                demisto.debug('Starting fetch with "/api/v2/events/data/" endpoint')
                new_last_run = get_all_events_async(
                    client=client, last_run=last_run, limit=max_fetch, all_event_types=all_event_types
                )
                demisto.debug(f"Fetched {len(all_event_types)} total events in {(datetime.utcnow() - start).seconds} seconds")
                
                # send_start = datetime.utcnow()
                # send_events_to_xsiam(
                # events=all_event_types, vendor=vendor, product=product, chunk_size=XSIAM_EVENT_CHUNK_SIZE_LIMIT
                # )
                # demisto.debug(f"Sent {len(all_event_types)} total events in {(datetime.utcnow() - send_start).seconds} seconds")
                
                demisto.debug(f"Handled {len(all_event_types)} total events in {(datetime.utcnow() - start).seconds} seconds")
                # next_trigger_time(len(all_event_types), max_fetch, new_last_run)
                demisto.debug(f"Setting the last_run to: {new_last_run}")
                # demisto.setLastRun(new_last_run)

            else:
                # We have this try-finally block for fetch events where wrapping up should be done if errors occur
                start = datetime.utcnow()
                try:
                    demisto.debug(f"Sending request with last run {last_run}")
                    new_last_run = get_all_events(
                        client=client, last_run=last_run, limit=max_fetch, all_event_types=all_event_types
                    )
                    demisto.debug("send_all_events_to_xsiam disabled in the POC integration")
                    # send_events_to_xsiam(
                    # events=all_event_types, vendor=vendor, product=product, chunk_size=XSIAM_EVENT_CHUNK_SIZE_LIMIT
                    # )
                finally:
                    demisto.debug(f"sending {len(all_event_types)} to xsiam")
                    demisto.debug("send_all_events_to_xsiam disabled in the POC integration")
                    # send_events_to_xsiam(
                    # events=all_event_types, vendor=vendor, product=product, chunk_size=XSIAM_EVENT_CHUNK_SIZE_LIMIT
                    # )

                    for (
                        event_type,
                        status,
                    ) in client.fetch_status.items():
                        if not status:
                            new_last_run[event_type] = {"operation": "resend"}

                    end = datetime.utcnow()

                    demisto.debug(f"Handled {len(all_event_types)} total events in {(end - start).seconds} seconds")
                    next_trigger_time(len(all_event_types), max_fetch, new_last_run)
                    demisto.debug(f"Setting the last_run to: {new_last_run}")
                    demisto.setLastRun(new_last_run)

    # Log exceptions and return errors
    except Exception as e:
        last_run = new_last_run if new_last_run else demisto.getLastRun()
        last_run.pop('nextTrigger', None)
        demisto.setLastRun(last_run)
        demisto.debug(f'last run after removing nextTrigger {last_run}')
        return_error(f'Failed to execute {command_name} command.\nError:\n{str(e)}')


''' ENTRY POINT '''

if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
