import argparse
import logging
import sys

import coloredlogs

from Tests.Marketplace.marketplace_constants import (
    AUTHORIZED_MARKETPLACES,
)


def validate_marketplace_variable(options: argparse.Namespace):
    marketplaces = options.marketplaces.split(",")
    unauthorized_mp = []
    for mp in marketplaces:
        logging.debug(f"Validating marketplace for {mp}")
        if mp not in AUTHORIZED_MARKETPLACES:
            unauthorized_mp.append(mp)

    if unauthorized_mp:
        raise ValueError(
            f"Got the following unauthorized marketplaces: {unauthorized_mp}.\nChoose from the following list only: "
            f"{AUTHORIZED_MARKETPLACES}"
        )


def run(options: argparse.Namespace):
    try:
        validate_marketplace_variable(options)
        logging.debug("variables were validated")

    except Exception as e:
        logging.error(e)
        sys.exit(1)


def options_handler(args=None):
    parser = argparse.ArgumentParser(
        description="Common validations for pipelines. " "Docs: <confluence link>"  # TODO
    )
    parser.add_argument(
        "--marketplaces", required=False, help="A comma seperated list of the relevant marketplaces " "to upload to."
    )
    options = parser.parse_args(args)

    return options


if __name__ == "__main__":
    coloredlogs.install(level="DEBUG", fmt="[%(levelname)s] - %(message)s")
    options = options_handler()
    run(options)
