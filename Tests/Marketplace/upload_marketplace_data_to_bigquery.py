import logging
import os
import traceback
from argparse import ArgumentParser
from collections.abc import Callable, Iterable, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from distutils.util import strtobool
from itertools import islice
from pathlib import Path
from time import time
from typing import Any

from demisto_sdk.commands.common.constants import MarketplaceVersions
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from neo4j import Driver, GraphDatabase

from Tests.scripts.utils.log_util import install_logging

NEO4J_URI = "bolt://localhost:7687"  # Default URI for local Neo4j
NEO4J_USER = "neo4j"  # Default username
NEO4J_PASSWORD = "contentgraph"  # Initial password

PROJECT_ID = os.getenv("XSOAR_CONTENT_BUILD_PROJECT") or "xdr-xsoar-content-dev-01"
DATASET_ID = os.getenv("MP_ANALYTICS_DATASET_ID") or "marketplace_analytics"
TABLE_ID = os.getenv("CONTENT_ITEMS_METADATA_TABLE_ID") or "content_items_data"

# Gets all content items of type `BaseContent``
ALL_BASECONTENT_QUERY = "MATCH (item: BaseContent) WHERE (item.hidden IS NULL OR item.hidden = false) RETURN item"

# Gets an integration's commands.
INTEGRATION_COMMANDS_QUERY = 'MATCH (i:Integration)-[:HAS_COMMAND]->(c:Command) WHERE i.object_id = "{object_id}" RETURN c.name'

# Checks if integration has mirroring commands.
HAS_MIRRORING_COMMANDS_QUERY = """
MATCH (i:Integration)-[:HAS_COMMAND]->(c:Command)
WHERE i.name = "{integration_name}" and c.name IN {command_names} RETURN c.name
"""

# Gets the playbooks using a content item.
GET_PLAYBOOKS_USING_ITEM_QUERY = (
    'MATCH (p:Playbook)-[:USES]->(item:{content_type}) WHERE item.object_id = "{object_id}" RETURN p.name'
)

# Gets the content items used by a playbook.
GET_ITEMS_USED_BY_PLAYBOOK_QUERY = (
    "MATCH (p:Playbook)-[:USES]->(item) "
    'WHERE p.object_id = "{object_id}"'
    "RETURN item.name, item.content_type, item.object_id"
)

# Gets the containing pack name.
GET_CONTAINING_PACK_QUERY = (
    "MATCH (item:BaseContent)-[:IN_PACK]->(pack:Pack) "
    'WHERE item.object_id = "{object_id}" AND item.content_type = "{content_type}" '
    "RETURN pack.name"
)

MARKETPLACES = list(MarketplaceVersions)
MIRRORING_COMMANDS = ["get-remote-data", "get-modified-remote-data", "update-remote-system"]

SCHEMA = [
    bigquery.SchemaField("alt_docker_images", "STRING", mode="REPEATED"),
    bigquery.SchemaField("associated_to_all", "BOOLEAN"),
    bigquery.SchemaField("associated_types", "STRING", mode="REPEATED"),
    bigquery.SchemaField("author", "STRING"),
    bigquery.SchemaField("author_image", "STRING"),
    bigquery.SchemaField("auto_update_docker_image", "BOOLEAN"),
    bigquery.SchemaField("categories", "STRING", mode="REPEATED"),
    bigquery.SchemaField("category", "STRING"),
    bigquery.SchemaField("certification", "STRING"),
    bigquery.SchemaField("cli_name", "STRING"),
    bigquery.SchemaField("close", "BOOLEAN"),
    bigquery.SchemaField("closure_script", "STRING"),
    bigquery.SchemaField("commands", "STRING", mode="REPEATED"),
    bigquery.SchemaField("commit", "STRING"),
    bigquery.SchemaField("content_global_id", "STRING"),
    bigquery.SchemaField("content_type", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("contributors", "STRING", mode="REPEATED"),
    bigquery.SchemaField("created", "STRING"),
    bigquery.SchemaField("current_version", "STRING"),
    bigquery.SchemaField("data_type", "STRING"),
    bigquery.SchemaField("days", "INTEGER"),
    bigquery.SchemaField("default_data_source_id", "STRING"),
    bigquery.SchemaField("definition_id", "STRING"),
    bigquery.SchemaField("definition_ids", "STRING", mode="REPEATED"),
    bigquery.SchemaField("dependency_packs", "STRING"),
    bigquery.SchemaField("deprecated", "BOOLEAN"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("details", "BOOLEAN"),
    bigquery.SchemaField("details_v2", "BOOLEAN"),
    bigquery.SchemaField("disable_monthly", "BOOLEAN"),
    bigquery.SchemaField("display_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("docker_image", "STRING"),
    bigquery.SchemaField("downloads", "INTEGER"),
    bigquery.SchemaField("edit", "BOOLEAN"),
    bigquery.SchemaField("email", "STRING"),
    bigquery.SchemaField("enhancement_script_names", "STRING", mode="REPEATED"),
    bigquery.SchemaField("eulaLink", "STRING"),
    bigquery.SchemaField("excluded_dependencies", "STRING", mode="REPEATED"),
    bigquery.SchemaField("execution_mode", "STRING"),
    bigquery.SchemaField("expiration", "INTEGER"),
    bigquery.SchemaField("field_type", "STRING"),
    bigquery.SchemaField("fromversion", "STRING"),
    bigquery.SchemaField("group", "STRING"),
    bigquery.SchemaField("has_mirroring", "BOOLEAN"),
    bigquery.SchemaField("hidden", "BOOLEAN"),
    bigquery.SchemaField("hours", "INTEGER"),
    bigquery.SchemaField("hybrid", "BOOLEAN"),
    bigquery.SchemaField("indicators_details", "BOOLEAN"),
    bigquery.SchemaField("indicators_quick_view", "BOOLEAN"),
    bigquery.SchemaField("integrations", "STRING", mode="REPEATED"),
    bigquery.SchemaField("is_beta", "BOOLEAN"),
    bigquery.SchemaField("is_feed", "BOOLEAN"),
    bigquery.SchemaField("is_fetch", "BOOLEAN"),
    bigquery.SchemaField("is_fetch_assets", "BOOLEAN"),
    bigquery.SchemaField("is_fetch_events", "BOOLEAN"),
    bigquery.SchemaField("is_fetch_events_and_assets", "BOOLEAN"),
    bigquery.SchemaField("is_fetch_samples", "BOOLEAN"),
    bigquery.SchemaField("is_mappable", "BOOLEAN"),
    bigquery.SchemaField("is_remote_sync_in", "BOOLEAN"),
    bigquery.SchemaField("is_silent", "BOOLEAN"),
    bigquery.SchemaField("is_test", "BOOLEAN"),
    bigquery.SchemaField("is_unified", "BOOLEAN"),
    bigquery.SchemaField("keywords", "STRING", mode="REPEATED"),
    bigquery.SchemaField("layout_id", "STRING"),
    bigquery.SchemaField("legacy", "BOOLEAN"),
    bigquery.SchemaField("long_running", "BOOLEAN"),
    bigquery.SchemaField("marketplaces", "STRING", mode="REPEATED"),
    bigquery.SchemaField("mobile", "BOOLEAN"),
    bigquery.SchemaField("modules", "STRING", mode="REPEATED"),
    bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("node_id", "STRING"),
    bigquery.SchemaField("not_in_repository", "BOOLEAN"),
    bigquery.SchemaField("object_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("os_type", "STRING"),
    bigquery.SchemaField("packs", "STRING", mode="REPEATED"),
    bigquery.SchemaField("pack", "STRING"),
    bigquery.SchemaField("path", "STRING"),
    bigquery.SchemaField("playbook", "STRING"),
    bigquery.SchemaField("playbooks", "STRING", mode="REPEATED"),
    bigquery.SchemaField("premium", "BOOLEAN"),
    bigquery.SchemaField("preview_only", "BOOLEAN"),
    bigquery.SchemaField("price", "INTEGER"),
    bigquery.SchemaField("profile_type", "STRING"),
    bigquery.SchemaField("python_version", "STRING"),
    bigquery.SchemaField("quick_view", "BOOLEAN"),
    bigquery.SchemaField("quiet", "BOOLEAN"),
    bigquery.SchemaField("regex", "STRING"),
    bigquery.SchemaField("reputation_script_name", "STRING"),
    bigquery.SchemaField("required", "BOOLEAN"),
    bigquery.SchemaField("runas", "STRING"),
    bigquery.SchemaField("search_rank", "INTEGER"),
    bigquery.SchemaField("search_window", "STRING"),
    bigquery.SchemaField("select_values", "STRING", mode="REPEATED"),
    bigquery.SchemaField("server_min_version", "STRING"),
    bigquery.SchemaField("skip_prepare", "STRING", mode="REPEATED"),
    bigquery.SchemaField("source_repo", "STRING"),
    bigquery.SchemaField("subtype", "STRING"),
    bigquery.SchemaField("support", "STRING"),
    bigquery.SchemaField("tags", "STRING", mode="REPEATED"),
    bigquery.SchemaField("tests", "STRING", mode="REPEATED"),
    bigquery.SchemaField("toversion", "STRING"),
    bigquery.SchemaField("type", "STRING"),
    bigquery.SchemaField("url", "STRING"),
    bigquery.SchemaField("use_cases", "STRING", mode="REPEATED"),
    bigquery.SchemaField("used_by_playbook", "STRING", mode="REPEATED"),
    bigquery.SchemaField("used_in_playbooks", "STRING", mode="REPEATED"),
    bigquery.SchemaField("version", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("videos", "STRING", mode="REPEATED"),
    bigquery.SchemaField("weeks", "INTEGER"),
    bigquery.SchemaField("widget_type", "STRING"),
]
NOT_RELEVANT_FIELDS: list[str] = ["updated", "select_values"]
DEFAULT_BATCH_SIZE: int = 1_000

ARTIFACTS_FOLDER: Path = Path(os.getenv("ARTIFACTS_FOLDER", "./artifacts"))
SUCCESS_FILE_PATH: Path = ARTIFACTS_FOLDER / "bigquery-upload-success.txt"
FAILURE_FILE_PATH: Path = ARTIFACTS_FOLDER / "bigquery-upload-failure.txt"


@dataclass
class Stats:
    """Class to store statistics for content items and marketplace packs."""

    mp_packs_distribution: dict[str, int] = field(default_factory=dict)
    content_items_count: int = 0
    packs_count: int = 0

    def summary(self) -> str:
        return (
            f"Total Content Items: {self.content_items_count}\n"
            f"Total Packs: {self.packs_count}\n"
            f"Marketplace Packs Distribution: {dict(self.mp_packs_distribution)}"
        )


def collect_data_for_sanity_check(item_data: dict, stats: Stats):
    """Collect data for sanity checks"""
    stats.content_items_count += 1
    if item_data["content_type"] == "Pack":
        stats.packs_count += 1
        for marketplace in item_data["marketplaces"]:
            if marketplace in MARKETPLACES:
                if marketplace not in stats.mp_packs_distribution:
                    stats.mp_packs_distribution[marketplace] = 0
                stats.mp_packs_distribution[marketplace] += 1


def run_query(neo4j_driver: Driver, query: str, parameters: dict[str, Any] | None = None) -> Iterator[dict]:
    """
    Runs a Cypher query against neo4j graphDB driver and return the results.
    """
    session = neo4j_driver.session()
    logging.debug(f"Running query: {query}")
    result = session.run(query, parameters)

    try:
        for record in result:
            yield record.data()
    finally:
        session.close()


def should_skip_item(item: dict) -> bool:
    """Determine if an item should be skipped based on its properties."""
    hidden = item.get("hidden", False)
    if isinstance(hidden, str):
        hidden = strtobool(hidden)
    return hidden or str(item["content_type"]).startswith("Test")


def enhance_content_item_with_pack_name(driver: Driver, item: dict) -> None:
    """Determine the pack name for the given content item."""
    if item["content_type"] == "Pack":
        item["pack"] = item["name"]
    else:
        pack_list: Iterator[dict] = run_query(
            driver, GET_CONTAINING_PACK_QUERY.format(object_id=item["object_id"], content_type=item["content_type"])
        )
        if pack_name_obj := next(pack_list, None):
            item["pack"] = pack_name_obj.get("pack.name", None)


def enhance_integration_data(driver: Driver, item: dict) -> None:
    """Enhance integration data with commands and mirroring information."""
    commands_objects = run_query(driver, INTEGRATION_COMMANDS_QUERY.format(object_id=item["object_id"]))
    item["commands"] = [command["c.name"] for command in commands_objects]
    item["has_mirroring"] = bool(
        run_query(driver, HAS_MIRRORING_COMMANDS_QUERY.format(integration_name=item["name"], command_names=MIRRORING_COMMANDS))
    )


def enhance_playbook_usage(driver: Driver, item: dict) -> None:
    """Add information about playbooks using this item."""
    playbook_ids = run_query(
        driver, GET_PLAYBOOKS_USING_ITEM_QUERY.format(content_type=item["content_type"], object_id=item["object_id"])
    )
    item["used_in_playbooks"] = [playbook_id["p.name"] for playbook_id in playbook_ids]


def enhance_playbook_items(driver: Driver, item: dict) -> None:
    """Add information about items used by this playbook."""
    items = run_query(driver, GET_ITEMS_USED_BY_PLAYBOOK_QUERY.format(object_id=item["object_id"]))
    item["used_by_playbook"] = [f"{item['item.name']}, {item['item.content_type']}, {item['item.object_id']}" for item in items]


def normalize_item_data(item: dict) -> None:
    """Normalize item data by removing not relevant fields."""
    for _field in NOT_RELEVANT_FIELDS:
        item.pop(_field, None)


CONTENT_TYPE_TO_ENHANCEMENT_FUNCTIONS: dict[str, list[Callable[[Driver, dict], None]]] = {
    "Integration": [enhance_integration_data, enhance_playbook_usage],
    "Script": [enhance_playbook_usage],
    "Command": [enhance_playbook_usage],
    "Playbook": [enhance_playbook_items],
}


def enhance_content_item_by_type(neo4j_driver: Driver, item_data: dict) -> None:
    """
    Enhance content item's data base on its type.
    Args:
        neo4j_driver (Driver): Neo4j driver object for database queries.
        item_data (dict): The content item data to be enhanced.
    """

    enhance_content_item_with_pack_name(neo4j_driver, item_data)

    content_type = item_data["content_type"]
    enhancement_functions: list[Callable[[Driver, dict], None]] = CONTENT_TYPE_TO_ENHANCEMENT_FUNCTIONS.get(content_type, [])
    for enhance in enhancement_functions:
        enhance(neo4j_driver, item_data)

    normalize_item_data(item_data)


def get_extra_content_items_data(neo4j_driver: Driver, content_items: list[dict], stats_object: Stats) -> list[dict]:
    """
    Enhances content items with additional data from the Content Graph.

    Each content item is processed and added extra information to, based on its type.
    Hidden items and test content are dropped.

    Args:
        neo4j_driver (Driver): Neo4j driver object for database queries.
        content_items (list[dict]): List of content item dictionaries to be enhanced.
        stats_objects (Stats): An object to collect data for sanity checks.

    Returns:
        list[dict]: A list of enhanced content item dictionaries.
    """
    logging.debug(f"Enhancing content items data for {len(content_items)} items")
    enhanced_content_items = []

    for content_item in content_items:
        if should_skip_item(content_item["item"]):
            logging.debug(f"Skipping item: {content_item['item']['name']}")
            continue
        item_data = deepcopy(content_item["item"])

        enhance_content_item_by_type(neo4j_driver, item_data)

        enhanced_content_items.append(item_data)

        collect_data_for_sanity_check(item_data, stats_object)

    return enhanced_content_items


def batch_iterable(iterable: Iterable[Any], batch_size: int = DEFAULT_BATCH_SIZE) -> Iterable[Any]:
    """Yield successive batches of size batch_size from iterable."""
    iterator = iter(iterable)
    while batch := list(islice(iterator, batch_size)):
        yield batch


def upload_to_bigquery(
    bq_client: bigquery.Client,
    dataset_ref: bigquery.DatasetReference,
    table_ref: bigquery.TableReference,
    driver: Driver,
    data: Iterator[dict[Any, Any]],
    stats_object: Stats,
) -> None:
    """
    Uploads content items data to BigQuery in batches.

    Populates the referenced table in batches.
    Ensures data integrity by uploading the data to a temporary table and copying it to the
    original table only if the process completes successfully.

    Args:
        bq_client (bigquery.Client): The BigQuery client instance.
        table_ref (bigquery.TableReference): Reference to the target BigQuery table.
        driver (neo4j.Driver): The Neo4j driver for querying additional data.
        data (Iterator): An iterator of content items to be uploaded.
        stats_object (Stats): An object to collect data for sanity checks.
    """
    temp_table_id = f"{TABLE_ID}_temp_{int(time())}"
    temp_table_ref = dataset_ref.table(temp_table_id)
    success = False
    batch_number = 0
    try:
        for batch_number, batch in enumerate(batch_iterable(data)):
            data_to_push = get_extra_content_items_data(driver, batch, stats_object)
            if batch_number == 0:
                # First batch overrides the table.
                job_config = bigquery.LoadJobConfig(autodetect=True, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
            else:
                job_config = bigquery.LoadJobConfig(
                    autodetect=True,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
                )

            job = bq_client.load_table_from_json(data_to_push, temp_table_ref, job_config=job_config)
            res = job.result()
            logging.info(f"Batch #{batch_number} (size {len(batch)}): {res.state}")
        success = True
        # Write success message to file for slack-notification:
        SUCCESS_FILE_PATH.write_text("Success")
    except Exception as e:
        logging.error(f"Got error while uploading batch #{batch_number}: {e}")
        logging.error(traceback.format_exc())
        # Write failure to file for slack-notification:
        FAILURE_FILE_PATH.write_text(str(e))
    finally:
        if success:
            copy_job_config = bigquery.CopyJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
            copy_job = bq_client.copy_table(temp_table_ref, table_ref, job_config=copy_job_config)
            copy_job.result()
            logging.info(f"Table {TABLE_ID} updated successfully.")

        # Cleanup temporary table
        bq_client.delete_table(temp_table_ref, not_found_ok=True)
        logging.info(f"Temporary table {temp_table_id} deleted.")


def get_dataset_reference(bq_client: bigquery.Client, dataset_id: str) -> bigquery.DatasetReference:
    """Fetches the dataset if it exists; otherwise, creates a new one."""
    dataset_ref = bq_client.dataset(dataset_id)
    try:
        dataset = bq_client.get_dataset(dataset_ref)
        logging.info(f"Dataset '{dataset_id}' exists.")
    except NotFound:
        logging.warning(f"Dataset '{dataset_id}' not found. Creating a new dataset.")
        dataset = bigquery.Dataset(dataset_ref)
        dataset = bq_client.create_dataset(dataset)
        logging.info(f"Dataset '{dataset_id}' created successfully.")

    # Return the dataset (existing or newly created)
    return dataset.reference


def get_table_reference(bq_client: bigquery.Client, dataset: bigquery.DatasetReference) -> bigquery.TableReference:
    """Fetches the table if it exists; otherwise, creates a new one."""
    # Create the table reference using dataset and table_id
    table_ref = dataset.table(TABLE_ID)
    try:
        table = bq_client.get_table(table_ref)
        logging.info(f"Table {table_ref} exists. Proceeding with data upload.")
    except NotFound:
        logging.warning("Table does not exist. Creating a new table.")
        table = bigquery.Table(table_ref, schema=SCHEMA)
        bq_client.create_table(table, exists_ok=True)

    # Return the table (whether it was fetched or created)
    return table_ref


def main():
    install_logging("upload_marketplace_data_to_bigquery.log", logger=logging)
    graph_db_driver = None
    stats_object = Stats()
    try:
        parser = ArgumentParser()
        parser.add_argument(
            "--force-upload",
            action="store_true",
            help="Force upload of data to BigQuery table, even if TEST_UPLOAD is set to true.",
        )
        args = parser.parse_args()

        graph_db_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        all_content_items_iterator: Iterator[dict] = run_query(graph_db_driver, ALL_BASECONTENT_QUERY)

        # We do not want to upload test data to the BQ table, unless explicitly sought.
        if not strtobool(os.getenv("TEST_UPLOAD", "false")) or args.force_upload:
            bq_client = bigquery.Client(project=PROJECT_ID)
            dataset_ref = get_dataset_reference(bq_client, DATASET_ID)
            table_ref = get_table_reference(bq_client, dataset_ref)
            upload_to_bigquery(bq_client, dataset_ref, table_ref, graph_db_driver, all_content_items_iterator, stats_object)

    except Exception as e:
        logging.error(f"An error occurred in the main function: {e!s}")
        FAILURE_FILE_PATH.write_text(f"Main function error: {e!s}")

    finally:
        logging.info(stats_object.summary())
        if graph_db_driver:
            graph_db_driver.close()


if __name__ == "__main__":
    main()
