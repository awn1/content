from collections.abc import Sequence

import tabulate
from more_itertools import chunked


def print_list_of_instances(
    instances: list[dict],
    index: bool = True,
    fields: Sequence[str] = ("name", "brand", "enabled"),
):
    """
    Output sample (with index=True):
        brand                     enabled     name
    --  ------------------------  ---------  ----------------------------------------------------------
    0  mail-sender                   true       Built-in Mail Sender
    1  SlackV3                       true       cached shmuel k
    2  Core REST API                 true       Core REST API_instance_1
    """
    print(
        tabulate.tabulate(
            (({k: v for k, v in instance.items() if k in fields}) for instance in instances),
            headers="keys",
            showindex="always" if index else "none",
        )
    )


def truncate(value: str, max_length: int = 50) -> str:
    return "\n".join("".join(chunk) for chunk in chunked(value, max_length))


def print_single_integration_instance(instance: dict, config_values: bool):
    """
    Output sample (excluding the first listing of instances, when config_values=True):

    brand    enabled    name
    -------  ---------  ---------------
    SlackV3  true       cached shmuel k
    ╭────────────────────────────────┬─────────────────╮
    │ key                            │ value           │
    ├────────────────────────────────┼─────────────────┤
    │ allow_incidents                │ False           │
    ├────────────────────────────────┼─────────────────┤
    │ demisto_api_key                │ None            │
    ├────────────────────────────────┼─────────────────┤
    │ disable_caching                │ False           │
    ├────────────────────────────────┼─────────────────┤
    │ enable_dm                      │ False           │
    ├────────────────────────────────┼─────────────────┤
    │ enable_outbound_file_mirroring │ False           │
    ├────────────────────────────────┼─────────────────┤
    """
    print_list_of_instances([instance], index=False)
    if config_values:
        values = instance["configvalues"]
        values = {k: truncate(str(v)) for k, v in values.items()}
        print(tabulate.tabulate({"key": values.keys(), "value": values.values()}, headers="keys", tablefmt="rounded_grid"))
