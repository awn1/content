import json
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import dotenv
import typer
from xlogs.commands.common import add_engine_prefix, logger, remove_engine_prefix

dotenv.load_dotenv(override=True)

warnings.filterwarnings("ignore", "Your application has authenticated using end user credentials")


app = typer.Typer(
    no_args_is_help=True,
    help="CLI tool for finding your way around Demisto logs easily. Uses user's own GCP permissions",
)

bundle_app = typer.Typer(no_args_is_help=True)
log_app = typer.Typer(no_args_is_help=True)

app.add_typer(bundle_app, name="bundle", help="Easier access to log bundles")
app.add_typer(log_app, name="log", help="Easier access to GCP logs")


@log_app.command("ask-permissions")
def ask_permission():
    """
    Send the required permissions requests required to the #xdr-permissions Slack chanel via Slack webhook.
    """
    from xlogs.commands.permissions.ask_permissions import ask_gcp_permissions

    ask_gcp_permissions()
    logger.info("permissions request sent to the #xdr-permissions chanel in Slack")


@log_app.command("engine")
def open_integration_logs(
    project_id: Annotated[
        str, typer.Argument(help="GCP project ID. `engine` will be prepended if the project doesn't already start with it.")
    ],
    integration_name: Annotated[str, typer.Argument(help="An integration to filter by")],
    days_back: int = 1,
    exact_integration_name: bool = False,
):
    """
    Generate a URL to conveniently search logs of a given integration brand. Adds summary fields and instance&brand filters.
    """
    project_id = add_engine_prefix(project_id)
    like_operator = "" if exact_integration_name else "~"

    print(
        "https://console.cloud.google.com/logs/query;"
        f'query=json_payload.sourceBrand%3D{like_operator}"{integration_name}";'
        "summaryFields=jsonPayload%252Fmsg:false:32:beginning;"
        "lfeCustomFields=jsonPayload%252FsourceInstance,jsonPayload%252FsourceBrand;"
        f"duration=P{days_back}D?project={project_id}"
    )


@log_app.command("tenant")
def open_tenant_integration_calls(project_id: str, query: str, days_back: int = 30):
    """
    Generate a URL to conveniently search logs of tenant integration calls.
    """
    print(
        f"https://console.cloud.google.com/logs/query;"
        f'query="{query}"%0A'
        'jsonPayload.logname="server.log";'
        f"&project={remove_engine_prefix(project_id)};"
        f"duration=P{days_back}D"
    )


@bundle_app.command("get")
def get_bundle(
    project_id: Annotated[str, typer.Argument(help="GCP project ID. `engine` prefix will be removed.")],
    bundle_password: Annotated[str, typer.Argument(envvar="DEMISTO_BUNDLE_PASSWORD", show_default=False)],
    dest_path_base: Annotated[
        Path, typer.Argument(file_okay=False, dir_okay=True, writable=True, help="Where to save the extracted bundle")
    ] = Path("/tmp/.log-bundles"),
    last_modified: datetime | None = None,
    last: Annotated[
        bool,
        typer.Option("-1", "-l", "--last", help="Provide to bring log bundles created on a certain date"),
    ] = False,
    force_download: Annotated[bool, typer.Option("--force", help="Download even if bundle already exists")] = False,
) -> Path:
    """
    Download and recursively unzip a log bundle, from a GCP project.
    """
    from xlogs.commands.bundle.bundle import download_and_extract
    from xlogs.commands.bundle.download import choose_bundle_blob, list_blobs

    blobs = list_blobs(remove_engine_prefix(project_id))
    if last_modified:
        blobs = tuple(filter(lambda blob: blob.time_created.date() == date, blobs))

    bundle_blob = choose_bundle_blob(blobs, last)
    return download_and_extract(project_id, bundle_password, dest_path_base, bundle_blob, force_download)


@bundle_app.command("instances")
def show_instance_info(
    project_id: str = typer.Option(default=None, help="GCP Project ID to download a log bundle from"),
    path: Path = typer.Option(
        file_okay=False,
        exists=True,
        dir_okay=True,
        default=None,
        help="Path to an extracted log bundle. Takes precedence over project ID.",
    ),
    brand: str = typer.Option(default=None, help="Filter instances by brand (case insensitive)"),
    bundle_password: str = typer.Argument(envvar="DEMISTO_BUNDLE_PASSWORD", show_default=False),
) -> None:
    """
    Show information about integration instances from a log bundle.
    """
    from xlogs.commands.bundle.integration_instances_json import print_list_of_instances, print_single_integration_instance

    if sum((bool(project_id), bool(path))) != 1:
        logger.error("Provide either project_id or path, but not both.")
        raise typer.Exit(1)

    if not path:
        path = get_bundle(project_id, bundle_password, last=True)

    instances = json.loads((path / "integrationInstances.json").read_text())
    if brand:
        instances = [instance for instance in instances if brand.lower() in instance["brand"].lower()]

    if len(instances) <= 3:
        for instance in instances:
            print_single_integration_instance(instance, config_values=True)

    else:
        print_list_of_instances(instances, index=True)
        choice = typer.prompt(input("Choose an instance index: "), type=int)
        print_single_integration_instance(instances[choice], config_values=True)


if __name__ == "__main__":
    app()
