import gzip
import os
import tempfile
from collections.abc import Generator
from gzip import GzipFile
from pathlib import Path
from time import time as get_current_time_in_seconds
from typing import NamedTuple
from zipfile import BadZipFile, ZipFile

import demistomock as demisto
import pytz
from CommonServerPython import *  # noqa # pylint: disable=unused-wildcard-import
from urllib3 import disable_warnings

from CommonServerUserPython import *  # noqa

disable_warnings()

# CONSTANTS
VENDOR = "symantec"
PRODUCT = "swg"
DEFAULT_FETCH_SLEEP = 30
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_CHUNK_SIZE_TO_READ = 1024 * 1024 * 400  # 400 MB
MAX_CHUNK_SIZE_TO_WRITE = 400 * (10**6)  # ~400 MB
TEST_MODULE_READ_CHUNK_SIZE = 2000  # 2 KB
STATUS_DONE = "done"
STATUS_MORE = "more"
STATUS_ABORT = "abort"

# REGEX
REGEX_FOR_STATUS = re.compile(r"X-sync-status: (?P<status>.*?)(?=\\r\\n|$)")
REGEX_FOR_TOKEN = re.compile(r"X-sync-token: (?P<token>.*?)(?=\\r\\n|$)")
START_RATIO = 17
PERCENT_BUFFER = 10
MAX_SIZE = 9 * 2**20  # 5 MB

class XSIAMCompressedChunkDeliver:

    def __init__(self, data) -> None:
        self.data = data
        self.element_size = len(data[0].encode("utf-8"))
        self.entrie_data_size = len(data) * self.element_size

    def convert_to_compressable_data(self, data: list) -> bytes:
        if data and isinstance(data[0], str):
            return "\n".join(data).encode()
        else:
            return "\n".join([json.dumps(event) for event in data]).encode()

    def compress_data(self, data: list[dict] | bytes):
        start = time.time()
        if isinstance(data, list):
            data = self.convert_to_compressable_data(data)
        return gzip.compress(data), time.time() - start

    def calculate_end_index(
        self,
        compression_ratio: float,
        start_index: int,
        percent_buffer: int,
        max_size: int,
    ) -> int:
        goal_size = (
            (100 - percent_buffer) * 0.01 * max_size * compression_ratio
        )  # for example: percent_buffer=20 -> 80 % from max_size * compression_ratio

        return (int(goal_size) // self.element_size) + start_index

    def get_compressed_chunks(
        self,
        compression_ratio: float = START_RATIO,
        percent_buffer: int = PERCENT_BUFFER,
        max_size: int = MAX_SIZE,
    ):
        """A generator for yielding a compressed chunks and thier comressed ratio

        Args:
            # data (list[dict]): The data to be chuked
            compression_ratio (int, optional): The compression ratio (not compressed // compressed). Defaults to START_RATIO.
            percent_buffer (int, optional): size in percent for buffering. Defaults to PERCENT_BUFFER.
            max_size (int, optional): the max size of an XSIAM entry. Defaults to MAX_SIZE.

        Yields:
            Generator: A generator yielding the compressed_data, compression_ratio
        """
        start_index = 0
        end_index = 0
        chunk_index = 1
        demisto.debug(
            f"entrie_data_size={self.entrie_data_size/2**20:.2f} MB ({len(self.data):,} items * {self.element_size=:,}), max_size={max_size/2**20} MB, {compression_ratio=}"
        )
        while start_index < len(self.data):
            end_index = self.calculate_end_index(
                compression_ratio, start_index, percent_buffer, max_size
            )
            end_index = min(end_index, len(self.data))
            before_compression_chunk = self.data[start_index:end_index]
            compressable_chunk = self.convert_to_compressable_data(
                before_compression_chunk
            )
            compressed_data, time_to_compress = self.compress_data(compressable_chunk)

            before_compression_size = len(compressable_chunk)
            compressed_size = len(compressed_data)

            demisto.debug(
                f"{chunk_index=:,}, {start_index=:,}, {end_index=:,}, {before_compression_size=:,}, {compressed_size=:,}, old_compression_ratio={compression_ratio:.2f}, new_compression_ratio={before_compression_size // compressed_size:.2f}, {time_to_compress=:.2f} sec"
            )
            compression_ratio = before_compression_size // compressed_size
            if compressed_size > max_size:
                demisto.debug(
                    f"❌ {chunk_index=} failure: {compressed_size=:,} > {max_size=:,}, setting the next compression_ratio to be {compression_ratio * 0.7:.2f} (0.7 * {compression_ratio=:.2f})"
                )
                compression_ratio = compression_ratio * 0.7
                # compression ratio was set, dont move forward with index, dont yield, do not pass go do not collect 200
                # consider manually throttling ratio, i vote yes

                continue
            # we all good here
            yield compressed_data, end_index - start_index
            start_index = end_index
            chunk_index += 1


def send_data_to_xsiam_test(data, vendor, product, data_format=None, url_key='url', num_of_attempts=3,
                    chunk_size=XSIAM_EVENT_CHUNK_SIZE, data_type=EVENTS, should_update_health_module=True,
                    add_proxy_to_request=False, snapshot_id='', items_count=None, multiple_threads=False):

    data_size = 0
    params = demisto.params()
    url = params.get(url_key)
    calling_context = demisto.callingContext.get('context', {})
    instance_name = calling_context.get('IntegrationInstance', '')
    collector_name = calling_context.get('IntegrationBrand', '')
    if not items_count:
        items_count = len(data) if isinstance(data, list) else 1
    if data_type not in DATA_TYPES:
        demisto.debug("data type must be one of these values: {types}".format(types=DATA_TYPES))
        return

    if not data:
        demisto.debug('send_data_to_xsiam function received no {data_type}, '
                    'skipping the API call to send {data} to XSIAM'.format(data_type=data_type, data=data_type))
        demisto.updateModuleHealth({'{data_type}Pulled'.format(data_type=data_type): data_size})
        return

    # only in case we have data to send to XSIAM we continue with this flow.
    # Correspond to case 1: List of strings or dicts where each string or dict represents an one event or asset or snapshot.
    if isinstance(data, list):
        # In case we have list of dicts we set the data_format to json and parse each dict to a stringify each dict.
        demisto.debug("Sending {size} {data_type} to XSIAM".format(size=len(data), data_type=data_type))
        if isinstance(data[0], dict):
            data = [json.dumps(item) for item in data]
            data_format = 'json'
        # Separating each event with a new line
        data = '\n'.join(data)
    elif not isinstance(data, str):
        raise DemistoException('Unsupported type: {data} for the {data_type} parameter.'
                            ' Should be a string or list.'.format(data=type(data), data_type=data_type))
    if not data_format:
        data_format = 'text'

    xsiam_api_token = demisto.getLicenseCustomField('Http_Connector.token')
    xsiam_domain = demisto.getLicenseCustomField('Http_Connector.url')
    xsiam_url = 'https://api-{xsiam_domain}'.format(xsiam_domain=xsiam_domain)
    headers = {
        'authorization': xsiam_api_token,
        'format': data_format,
        'product': product,
        'vendor': vendor,
        'content-encoding': 'gzip',
        'collector-name': collector_name,
        'instance-name': instance_name,
        'final-reporting-device': url,
        'collector-type': ASSETS if data_type == ASSETS else EVENTS
    }
    if data_type == ASSETS:
        if not snapshot_id:
            snapshot_id = str(round(time.time() * 1000))

        # We are setting a time stamp ahead of the instance name since snapshot-ids must be configured in ascending
        # alphabetical order such that first_snapshot < second_snapshot etc.
        headers['snapshot-id'] = snapshot_id + instance_name
        headers['total-items-count'] = str(items_count)

    header_msg = 'Error sending new {data_type} into XSIAM.\n'.format(data_type=data_type)

    def data_error_handler(res):
        """
        Internal function to parse the XSIAM API errors
        """
        try:
            response = res.json()
            error = res.reason
            if response.get('error').lower() == 'false':
                xsiam_server_err_msg = response.get('error')
                error += ": " + xsiam_server_err_msg

        except ValueError:
            if res.text:
                error = '\n{}'.format(res.text)
            else:
                error = "Received empty response from the server"

        api_call_info = (
            'Parameters used:\n'
            '\tURL: {xsiam_url}\n'
            '\tHeaders: {headers}\n\n'
            'Response status code: {status_code}\n'
            'Error received:\n\t{error}'
        ).format(xsiam_url=xsiam_url, headers=json.dumps(headers, indent=8), status_code=res.status_code, error=error)

        demisto.error(header_msg + api_call_info)
        raise DemistoException(header_msg + error, DemistoException)

    client = BaseClient(base_url=xsiam_url, proxy=add_proxy_to_request)

    def send_events(zipped_data):
        xsiam_api_call_with_retries(client=client, events_error_handler=data_error_handler,
                                    error_msg=header_msg, headers=headers,
                                    num_of_attempts=num_of_attempts, xsiam_url=xsiam_url,
                                    zipped_data=zipped_data, is_json_response=True, data_type=data_type)

    demisto.info("Sending events to xsiam with a single thread.")
    compressor = XSIAMCompressedChunkDeliver(data)
    for chunk, size in compressor.get_compressed_chunks():
        data_size += size
        send_events(chunk)

    demisto.debug(f"Sending chunk of {size} events to XSIAM")
    if should_update_health_module:
        demisto.updateModuleHealth({f'{data_type}Pulled': data_size})
    return

def send_events_to_xsiam_test(events, vendor, product, data_format=None, url_key='url', num_of_attempts=3,
                         chunk_size=XSIAM_EVENT_CHUNK_SIZE, should_update_health_module=True,
                         add_proxy_to_request=False, multiple_threads=False):

    return send_data_to_xsiam_test(
        events,
        vendor,
        product,
        data_format,
        url_key,
        num_of_attempts,
        chunk_size,
        data_type="events",
        should_update_health_module=should_update_health_module,
        add_proxy_to_request=add_proxy_to_request,
        multiple_threads=multiple_threads
    )

class LastRun(NamedTuple):
    start_date: str | None = None
    token: str | None = None
    time_of_last_fetched_event: str | None = None
    events_suspected_duplicates: list[str] | None = None
    token_expired: bool = False


class HandlingDuplicates(NamedTuple):
    max_time: str = ""
    events_suspected_duplicates: list[str] = []

    def is_duplicate(
        self,
        id_: str,
        cur_time: str,
    ) -> bool:
        """
        Checks whether the event already fetched if so returns True otherwise False

        Args:
            id_ (str): id of the event
            cur_time (str): the time of the event
            time_of_last_fetched_event (str): The time of the last event that already fetched
            events_suspected_duplicates (list[str]): The ids of all events from the latest time of the last fetch
        """

        # The event time is later than the late time of the last fetch
        if cur_time > self.max_time:
            return False

        # The time of the event is equal to the late time of the last fetch,
        # checks if its id is there is in the list of events that have already been fetched
        return not (cur_time == self.max_time and id_ not in self.events_suspected_duplicates)


class Client(BaseClient):
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        verify: bool,
        proxy: bool,
        fetch_interval: str | None,
    ) -> None:
        headers: dict[str, str] = {"X-APIUsername": username, "X-APIPassword": password}
        super().__init__(base_url=base_url, verify=verify, proxy=proxy, headers=headers, timeout=180)

        self.fetch_interval = get_fetch_interval(fetch_interval)

    def get_logs(self, params: dict[str, Any]):
        """
        API call in streaming to fetch events
        """
        return self._http_request(
            method="GET",
            url_suffix="/reportpod/logs/sync",
            params=params,
            resp_type="response",
            stream=True,
        )


""" HELPER FUNCTIONS """


def get_fetch_interval(fetch_interval: str | None) -> int:
    """Returns the fetch interval in seconds"""
    fetch_sleep = arg_to_number(fetch_interval)
    if not fetch_sleep:
        return DEFAULT_FETCH_SLEEP
    if fetch_sleep < DEFAULT_FETCH_SLEEP:
        demisto.debug(f"Fetch interval is too low, setting it to minimum of {DEFAULT_FETCH_SLEEP} seconds")
        return DEFAULT_FETCH_SLEEP
    return fetch_sleep


def get_events_and_write_to_file_system(
    client: Client,
    params: dict,
) -> Path:
    """
    Writing the events that come from the API to a temporary file.
    Return:
        Path: the file path
    """
    with client.get_logs(params) as res, tempfile.NamedTemporaryFile(mode="wb", delete=False) as tmp_file:
        # Write the chunks from the response to the tmp file
        for chunk in res.iter_content(chunk_size=MAX_CHUNK_SIZE_TO_WRITE):
            tmp_file.write(chunk)

    return Path(tmp_file.name)


def get_start_and_end_date(start_date: str | None) -> tuple[int, int]:
    """
    returns `start_date` and `end_date`

    Args:
        start_date (str | None): start_date which is stored in the last_run object from the second run onwards

    Returns:
        tuple[int, int]: start_date, end_date
    """
    # set the end_date to the current time
    now = datetime.now().astimezone(pytz.utc)

    # If there is no `start_date` stored in the `last_run` object,
    # sets the `start_date` to one minute before the current time
    start_date = int(start_date or date_to_timestamp(now - timedelta(minutes=1)))

    # convert the end_date to timestamp
    end_date = date_to_timestamp(date_str_or_dt=now)

    return start_date, end_date


def get_status_and_token_from_file(file_path: Path) -> tuple[str, str]:
    """
    Extracting the status and the next_token.
    """

    # Getting the file size to read only its end for the `status` and `next_token`
    file_size = file_path.stat().st_size
    read_size = 2000
    if file_size < read_size:  # In case the file is smaller than 2000 bytes
        read_size = file_size

    # Reading end of file
    with file_path.open("rb") as tmp_file:
        tmp_file.seek(file_size - read_size)
        end_file = tmp_file.read()

    # Extracting the `status` and the `next_token` by regex
    status = ""
    token = ""
    if status_match := REGEX_FOR_STATUS.search(str(end_file)):
        status = status_match.groupdict().get("status", "")
    if token_match := REGEX_FOR_TOKEN.search(str(end_file)):
        token = token_match.groupdict().get("token", "")

    return status, token


def get_the_last_row_that_incomplete(lines: list[bytes], file_size: int) -> bytes:
    """
    Args:
        lines (list[bytes]): The list of lines read so far.
        file_size (int): The total size of the file being read.

    Returns:
        bytes: The last incomplete line if one exists, empty bytes otherwise.
    """
    if lines and not lines[-1].endswith(b"\n") and file_size > 0:
        return lines[-1]
    return b""


def extract_logs_from_zip_file(file_path: Path) -> Generator[list[bytes], None, None]:
    """Extracts logs from the response ZIP file.

    Tries to open the file path as a ZIP file.
    Iterates through contained files looking for gzipped files.
    Opens each gzipped file and reads it in batches,
    yielding a list of raw log lines for each batch.

    Handles BadZipFile exception if file is not a valid ZIP:
        - Checks if file content indicates no logs returned from API
        - Otherwise raises ValueError that file is not a ZIP

    Args:
        file_path: Path to the ZIP file containing gzipped log files.

    Yields:
        list[bytes]: A batch of raw log lines read from a gzipped file.
    """
    demisto.debug(f"The file path: {file_path.name}")
    try:
        # extract the ZIP file
        with ZipFile(file_path, "r") as outer_zip:
            # iterate all gzip files
            for file in outer_zip.infolist():
                # check if the file is gzip
                if file.filename.lower().endswith(".gz"):
                    try:
                        with outer_zip.open(file) as nested_zip_file, gzip.open(nested_zip_file, "rb") as f:
                            file_size = get_size_gzip_file(f)
                            remaining_last_line_part: bytes = b""
                            while file_size > 0:
                                # Get the chunk size for reading from the file,
                                # limited to MAX_CHUNK_SIZE_TO_READ or less
                                chunk = min(file_size, MAX_CHUNK_SIZE_TO_READ)

                                # Subtracting the chunk to be read from the size of the file
                                file_size -= chunk

                                # Reads a chunk of data from the gzip file.
                                try:
                                    raw_event_parts = f.read(chunk).splitlines()
                                except Exception as e:
                                    demisto.debug(f"Error occurred while reading file: {e}")
                                    break

                                # Concatenates any remaining last line from previous batch
                                # to the first line of current batch to handle log lines split across batches
                                if remaining_last_line_part:
                                    raw_event_parts[0] = remaining_last_line_part + raw_event_parts[0]

                                # Checks if the last line is incomplete and saves it for concatenating
                                # with the next batch. Yields the current batch without the incomplete line.
                                # If no incomplete line, resets the remaining line part and yields the batch.
                                if remaining_last_line_part := get_the_last_row_that_incomplete(raw_event_parts, file_size):
                                    yield raw_event_parts[:-1]
                                else:
                                    remaining_last_line_part = b""
                                    yield raw_event_parts
                    except Exception as e:
                        demisto.debug(f"Crashed at the open the internal file {file.filename} file, Error: {e}")
                else:  # the file is not gzip
                    demisto.debug(f"The {file.filename} file is not of gzip type")
    except BadZipFile as e:
        content = file_path.read_bytes()
        if content.startswith((b"X-sync-status", b"X-sync-token")):  # No logs
            demisto.debug("No logs returned from the API")
        else:
            raise ValueError(f"The external file type is not of type ZIP, Error: {e}")
    except Exception as e:
        raise ValueError(f"There is no specific error for the crash, Error: {e}")


def get_size_gzip_file(f: GzipFile) -> int:
    # Get size of gzip file by seeking to end and getting current position
    f.seek(0, os.SEEK_END)
    file_size = f.tell()
    demisto.debug(f"size of gzip file: {file_size / (1024 ** 2):.2f} MB")

    # Return the pointer position to the beginning of the file
    f.seek(0)

    return file_size


def parse_events(
    logs: list[bytes],
    token_expired: bool,
    time_of_last_fetched_event: str,
    new_events_suspected_duplicates: list[str],
    handling_duplicates: HandlingDuplicates = HandlingDuplicates(),
) -> tuple[list[str], str]:
    """Parses raw log events into a list of event strings.

    In case the token is expired it filters duplicate events based on timestamp and ID

    Args:
        logs: The raw log events as bytes
        token_expired: Whether the API token has expired
        time_of_last_fetched_event: The timestamp of the last fetched event
        events_suspected_duplicates: List of event IDs suspected as duplicates
        new_events_suspected_duplicates: Output list for new suspected dups

    Returns:
        events: List of parsed event strings
        max_time: Timestamp of latest event
    """
    events: list[str] = []
    max_time = time_of_last_fetched_event

    demisto.debug(f"The len of the events before filter {len(logs)}")
    for log in logs:
        # Decodes the raw log event bytes to a string
        event = log.decode()

        # each line that starts with '#' is a header, skip it
        if event.startswith("#"):
            continue

        parts = event.split(" ")

        # Parses Date and ID from log event.
        try:
            cur_time = f"{parts[1]} {parts[2]}"
            id_ = parts[-1]
        except Exception as e:
            raise ValueError(f"Error occurred while splitting event: {e} -> {event}")

        # In case that token is expired, checks if the event is a duplicate,
        # if so skips the event
        if token_expired and handling_duplicates.is_duplicate(
            id_=id_,
            cur_time=cur_time,
        ):
            continue

        # management the list of ids and the time of the last event
        if cur_time > max_time:
            new_events_suspected_duplicates.clear()
            new_events_suspected_duplicates.append(id_)
            max_time = cur_time
        elif cur_time == max_time:
            new_events_suspected_duplicates.append(id_)

        events.append(event)

    demisto.debug(f"The len of the events after filter {len(events)}")
    return events, max_time


def get_start_date_for_next_fetch(start_date: int, time_of_last_fetched_event: str) -> int:
    """
    Calculates the start date for the next fetch based on the last fetched event time.
    If last fetched event time is valid datetime, converts to timestamp.
    Otherwise defaults to original `start_date`.
    """
    if time_of_last_fetched_event:
        # Converts the `time_of_last_fetched_event` to a timestamp
        # to use for the start date of the next fetch.
        try:
            start_date_for_next_fetch = date_to_timestamp(
                date_str_or_dt=time_of_last_fetched_event,
                date_format=DATE_FORMAT,
            )
        except Exception:
            # If the conversion fails,
            # defaults to the original start date.
            demisto.debug("time_of_last_fetched_event is not datetime")
            start_date_for_next_fetch = start_date
    else:
        start_date_for_next_fetch = start_date
    return start_date_for_next_fetch


def calculate_next_fetch(
    start_date: int,
    new_token: str,
    time_of_last_fetched_event: str,
    new_events_suspected_duplicates: list[str],
    handling_duplicates: HandlingDuplicates,
    token_expired: bool,
):
    """
    Updates the integration context with the information
    needed for the next fetch.

    It handles updating the duplicate event tracking if a newer event time is seen.

    Returns a LastRun object containing the data for the next run.
    """

    start_date_for_next_fetch = get_start_date_for_next_fetch(start_date, time_of_last_fetched_event)

    if time_of_last_fetched_event > handling_duplicates.max_time:
        # A newer event time was seen, reset duplicate tracking
        new_last_run_model = LastRun(
            start_date=str(start_date_for_next_fetch),
            token=str(new_token),
            time_of_last_fetched_event=str(time_of_last_fetched_event),
            events_suspected_duplicates=new_events_suspected_duplicates,
        )

    elif time_of_last_fetched_event == handling_duplicates.max_time:
        # Newer event time is not visible, keep duplicate existing tracking
        # plus the new ids retrieved with the same time
        new_last_run_model = LastRun(
            start_date=str(start_date_for_next_fetch),
            token=str(new_token),
            time_of_last_fetched_event=handling_duplicates.max_time,
            events_suspected_duplicates=handling_duplicates.events_suspected_duplicates + new_events_suspected_duplicates,
            token_expired=token_expired,
        )

    else:
        # Newer or equal event time is not visible, keep duplicate existing tracking
        new_last_run_model = LastRun(
            start_date=str(start_date_for_next_fetch),
            token=str(new_token),
            time_of_last_fetched_event=handling_duplicates.max_time,
            events_suspected_duplicates=handling_duplicates.events_suspected_duplicates,
            token_expired=token_expired,
        )

    # Updates the integration context with the new LastRun model.
    set_integration_context({"last_run": new_last_run_model._asdict()})

    return new_last_run_model


def extract_logs_and_push_to_XSIAM(
    last_run_model: LastRun, tmp_file_path: Path, token_expired: bool
) -> tuple[str, list[str], HandlingDuplicates]:
    """Extracts logs from the zip file downloaded from the API, parses the events,
    and sends them to XSIAM in batches if any events exist.

    Args:
        last_run_model: The last run model containing the state of the previous run.
        tmp_file_path: The path to the temporary zip file downloaded from the API.
        token_expired: Whether the API token has expired.

    Returns:
        A tuple containing:
        - The time of the last fetched event.
        - A list of event IDs suspected to be duplicates.
        - The handling_duplicates object containing state about duplicate handling.
    """
    # Initialize variables
    new_events_suspected_duplicates: list[str] = []
    time_of_last_fetched_event: str = last_run_model.time_of_last_fetched_event or ""
    handling_duplicates = HandlingDuplicates(
        max_time=time_of_last_fetched_event,
        events_suspected_duplicates=last_run_model.events_suspected_duplicates or [],
    )

    # Extracts logs from the zip file downloaded from the API, parses the events,
    # sends them to XSIAM in batches if any events exist.
    for part_logs in extract_logs_from_zip_file(tmp_file_path):
        try:
            # Parse the events
            (
                events,
                time_of_last_fetched_event,
            ) = parse_events(
                part_logs,
                token_expired,
                time_of_last_fetched_event,
                new_events_suspected_duplicates,
                handling_duplicates=handling_duplicates,
            )
        except Exception as e:
            demisto.info(f"Error parsing events: {e}")
            raise e

        try:
            if events:
                # Send events to XSIAM in batches
                send_events_to_xsiam_test(
                    events,
                    VENDOR,
                    PRODUCT,
                    chunk_size=XSIAM_EVENT_CHUNK_SIZE_LIMIT // 2,
                )
                demisto.debug(f"len of the events is: {len(events)}")
        except Exception as e:
            demisto.info(f"Failed to send events to XSOAR. Error: {e}")
            raise e

    return (
        time_of_last_fetched_event,
        new_events_suspected_duplicates,
        handling_duplicates,
    )


""" FETCH EVENTS """


def get_events_command(
    client: Client,
    last_run_model: LastRun,
) -> None:
    # Make API call in streaming to fetch events and writing to a temporary file on the disk.
    status = STATUS_MORE
    while status != STATUS_DONE:
        token_expired = last_run_model.token_expired

        # Set the fetch times, where the `end_time` is consistently set to the current time.
        # The `start_time` is determined by the `last_run`,
        # and if it does not exist, it is set to one minute prior.
        start_date, end_date = get_start_and_end_date(start_date=last_run_model.start_date)

        # Set the parameters for the API call
        params: dict[str, Union[str, int]] = {
            "startDate": start_date,
            "endDate": end_date,
            "token": last_run_model.token or "none",
        }
        try:
            try:
                tmp_file_path = get_events_and_write_to_file_system(
                    client,
                    params,
                )
            except DemistoException as e:
                try:
                    if e.res is not None and e.res.status_code == 410:
                        # In case the token expired
                        # Update last run model with expired_token = True
                        # for handling duplicates in next fetch
                        demisto.debug(f"The token has expired: {e}")
                        last_run_model = LastRun(
                            start_date=str(start_date),
                            token="none",
                            time_of_last_fetched_event=last_run_model.time_of_last_fetched_event,
                            events_suspected_duplicates=last_run_model.events_suspected_duplicates,
                            token_expired=True,
                        )
                        continue
                    elif e.res is not None and e.res.status_code == 423:
                        demisto.debug(f"API access is blocked: {e}")
                        time.sleep(client.fetch_interval)
                        continue
                    elif e.res is not None and e.res.status_code == 429:
                        demisto.debug(f"Call refused due to limit of api calls: {e}")
                        time.sleep(client.fetch_interval)
                        continue
                    else:
                        demisto.info(f"ERROR: {e=}")
                        raise e
                except Exception as err:
                    demisto.debug(f"ERROR: {e=} after the error: {err}")
                    raise e
            except Exception as err:
                raise err

            status, new_token = get_status_and_token_from_file(tmp_file_path)

            # If status is "abort", deletes the tmp file
            # and continue the loop to fetch with the same parameters.
            if status == STATUS_ABORT:
                tmp_file_path.unlink()
                continue

            (
                time_of_last_fetched_event,
                new_events_suspected_duplicates,
                handling_duplicates,
            ) = extract_logs_and_push_to_XSIAM(last_run_model, tmp_file_path, token_expired)
        except Exception as e:
            if tmp_file_path.exists():
                tmp_file_path.unlink()
            else:
                try:
                    tmp_file_path.unlink()
                except Exception:
                    demisto.debug("No file to unlink")
            raise e
        # Removes the tmp file
        tmp_file_path.unlink()
        demisto.debug("Temporary file unlinked successfully")

        last_run_model = calculate_next_fetch(
            start_date,
            new_token,
            time_of_last_fetched_event,
            new_events_suspected_duplicates,
            handling_duplicates,
            token_expired=token_expired,
        )


""" TEST MODULE """


def test_module(client: Client, fetch_interval: str | None) -> str:
    # Enforcement for the fetch_interval parameter
    # that will not be less than the minimum time allowed
    if fetch_interval and int(fetch_interval) < DEFAULT_FETCH_SLEEP:
        raise ValueError(
            f"The minimum fetch interval is {DEFAULT_FETCH_SLEEP} seconds"
            "Please increase the fetch_interval value and try again."
        )

    start_date, end_date = get_start_and_end_date(None)
    params: dict[str, Union[str, int]] = {
        "startDate": start_date,
        "endDate": end_date,
        "token": "none",
    }

    # In order to shorten the test time It attempts to retrieve a small chunk of logs.
    # If successful, it returns `ok`, otherwise it raises an exception
    # with details of the reason.
    try:
        with client.get_logs(params) as res:
            for _ in res.iter_content(chunk_size=TEST_MODULE_READ_CHUNK_SIZE):
                return "ok"
    except DemistoException as e:
        if e.res is not None and (e.res.status_code == 423 or e.res.status_code == 429):
            return "ok"
        elif "HTTP Status 401" in str(e):
            raise ValueError("Authorization Error: make sure API Key is correctly set")
        else:
            raise e
    except Exception as e:
        if "HTTP Status 401" in str(e):
            raise ValueError("Authorization Error: make sure API Key is correctly set")
        else:
            raise e
    return "ok"


def perform_long_running_loop(client: Client):
    last_run_obj: LastRun
    while True:
        # Used to calculate the duration of the fetch run.
        start_run = get_current_time_in_seconds()
        try:
            integration_context = get_integration_context()
            demisto.debug(f"Starting new fetch with {integration_context=}")
            integration_context = integration_context.get("last_run")
            last_run_obj = LastRun(**integration_context) if integration_context else LastRun()

            get_events_command(client, last_run_obj)

        except Exception as e:
            demisto.debug(f"Failed to fetch logs from API. Error: {e}")
            raise e

        # Used to calculate the duration of the fetch run.
        end_run = get_current_time_in_seconds()

        # Calculation of the fetch runtime against `client.fetch_interval`
        # If the runtime is less than the `client.fetch_interval` time
        # then it will go to sleep for the time difference
        # between the `client.fetch_interval` and the fetch runtime
        # Otherwise, the next fetch will occur immediately
        if (fetch_sleep := client.fetch_interval - (end_run - start_run)) > 0:
            time.sleep(fetch_sleep)


def main() -> None:  # pragma: no cover
    params = demisto.params()

    base_url = params["url"].strip("/")
    username = params["credentials"]["identifier"]
    password = params["credentials"]["password"]
    verify = not argToBoolean(params.get("insecure", False))
    proxy = argToBoolean(params.get("proxy", False))
    fetch_interval = params.get("fetch_interval")

    command = demisto.command()
    try:
        client = Client(
            base_url=base_url,
            username=username,
            password=password,
            verify=verify,
            proxy=proxy,
            fetch_interval=fetch_interval,
        )

        if command == "test-module":
            return_results(test_module(client, fetch_interval))
        if command == "long-running-execution":
            # integration_context = get_integration_context()
            # demisto.debug(f"{integration_context=}")
            demisto.debug("Starting long running execution")
            # set_integration_context({})
            # demisto.debug("The integration context has been reset")
            # time.sleep(300)
            perform_long_running_loop(client)
        else:
            raise NotImplementedError(f"Command {command} is not implemented.")

    except Exception as e:
        return_error(
            f"Failed to execute {command} command. Error in Symantec Web Security Service Event Collector Integration [{e}]."
        )


""" ENTRY POINT """

if __name__ in ("__main__", "__builtin__", "builtins"):
    main()
