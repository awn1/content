import argparse
import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.dates import DayLocator
from matplotlib.ticker import MultipleLocator
from slack_sdk import WebClient

from Tests.scripts.utils.slack import get_messages_from_slack

# 50 unique colors to select from
COLORS_PALETTE = [
    "red",
    "blue",
    "green",
    "orange",
    "purple",
    "yellow",
    "pink",
    "brown",
    "black",
    "gray",
    "cyan",
    "magenta",
    "olive",
    "lime",
    "teal",
    "indigo",
    "maroon",
    "navy",
    "peru",
    "sienna",
    "tan",
    "thistle",
    "violet",
    "wheat",
    "yellowgreen",
    "aquamarine",
    "bisque",
    "blanchedalmond",
    "blueviolet",
    "burlywood",
    "cadetblue",
    "chartreuse",
    "chocolate",
    "coral",
    "cornflowerblue",
    "cornsilk",
    "crimson",
    "darkblue",
    "darkcyan",
    "darkgoldenrod",
    "darkgray",
    "darkgreen",
    "darkkhaki",
    "darkmagenta",
    "darkolivegreen",
    "darkorange",
    "darkorchid",
    "darkred",
    "darksalmon",
    "darkseagreen",
    "darkslateblue",
]
LOCK_DURATION = "Lock Duration"
AVAILABLE_MACHINES = "Available machines"
JOB_ID = "Job ID"
BUILD_IN_QUEUE = "Builds in queue"
TIMESTAMP = "Timestamp (UTC)"
IMAGE_EXTENSION = ".png"
LOCK_DURATION_GRAPH_FILE_NAME = "lock_duration_graph"
AVAILABLE_MACHINES_GRAPH_FILE_NAME = "available_machines_graph"
BUILDS_WAITING_IN_QUEUE_GRAPH_FILE_NAME = "builds_waiting_in_queue_graph"

logger = logging.getLogger(__name__)


def remove_anomalies(
    data_raw: list, timestamps_raw: list, types_raw: list, z_score_threshold: int = 3
) -> tuple[list, list, list]:
    df = pd.DataFrame(
        {
            "data": data_raw,
            "types": types_raw,
            "timestamps": timestamps_raw,
        }
    )
    mean = df["data"].mean()
    std = df["data"].std()
    z_score = (df["data"] - mean) / std
    data = list(map(float, df["data"][z_score.abs() < z_score_threshold].values))
    types = list(df["types"][z_score.abs() < z_score_threshold].values)
    timestamps = list(df["timestamps"][z_score.abs() < z_score_threshold].values)
    return data, timestamps, types


def generate_timestamps_labels(timestamps: list) -> list[datetime]:
    return [datetime.strptime(item, "%Y-%m-%dT%H:%M:%S.%f") for item in timestamps]


def calculate_mean_values(types: list, values: list) -> dict[str, float]:
    # Group values by type
    type_values: dict[str, list] = defaultdict(list)
    for type_, value in zip(types, values):
        type_values[type_].append(value)

    return {type_: float(np.mean(type_duration)) for type_, type_duration in type_values.items()}


def sanitized_type(type_: str) -> str:
    return type_.replace("content-locks/", "").replace("locks-", "").replace("-", " ").upper()


def assign_colors_to_types(types: list[str]) -> tuple[list[str], dict[str, str]]:
    available_colors = list(COLORS_PALETTE)
    type_colors = {}
    types_with_color = []
    for type_ in types:
        sanitized_type_ = sanitized_type(type_)
        if sanitized_type_ not in type_colors:
            if not available_colors:
                raise ValueError("Not enough colors to assign to all types")
            type_colors[sanitized_type_] = available_colors.pop()
        types_with_color.append(type_colors[sanitized_type_])
    return types_with_color, type_colors


def plot_graph(
    data: list,
    types: list,
    timestamps: list,
    title: str,
    x_label: str,
    y_label: str,
    file_name: Path,
    y_lim: float | None = None,
) -> tuple[dict[str, float], list[str], dict[str, str]]:
    types_with_color, type_colors = assign_colors_to_types(types)
    plt.clf()
    plt.legend(
        handles=[
            plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=color, markersize=6, label=type_)
            for type_, color in type_colors.items()
        ],
        loc="center left",
        bbox_to_anchor=(1.05, 0),
        fontsize=7,
        borderaxespad=0.0,
    )
    plt.scatter(
        x=generate_timestamps_labels(timestamps),  # type: ignore[arg-type]
        y=data,
        c=types_with_color,
        label=types_with_color,
    )
    mean_values = calculate_mean_values(types, data)
    for type_, mean_value in mean_values.items():
        sanitized_type_ = sanitized_type(type_)
        color = type_colors[sanitized_type_]
        logger.info(f"{type_=} {sanitized_type_=} {color=}")
        plt.axhline(y=mean_value, color=color, linestyle="--", label=f"Mean {type_}")  # Adjust line style and color as needed

    plt.gca().xaxis.set_major_locator(DayLocator(interval=2))  # Adjust the interval as needed
    if y_lim:
        plt.ylim(0, y_lim)
    else:
        plt.gca().yaxis.set_major_locator(MultipleLocator(2))
    plt.xticks(fontsize=6)  # Adjust the fontsize value as needed
    plt.gcf().autofmt_xdate()
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.tight_layout()
    plt.title = title
    plt.savefig(file_name.as_posix())
    plt.show()
    return mean_values, types_with_color, type_colors


def save_graph_data(file_name: Path, data: list, types: list, timestamps: list, mean_values: dict[str, float]):
    points = [
        {
            "data": data_point,
            "type": type_,
            "timestamp": timestamp,
        }
        for data_point, type_, timestamp in zip(data, types, timestamps)
    ]
    with open(file_name, "w") as file_handle:
        json.dump(
            {
                "mean_values": mean_values,
                "points": points,
            },
            file_handle,
            indent=4,
            default=str,
            sort_keys=True,
        )


def create_lock_duration_graph(
    messages: list[str], graph_output_path: Path
) -> tuple[list[float], list[str], dict[str, str], dict[str, float], Path, Path]:
    data_raw, types_raw, timestamps_raw = [], [], []

    for message in messages:
        if LOCK_DURATION in message:
            message_split = message.split("\n")
            timestamps_raw.append(message_split[1])
            types_raw.append(message_split[2])
            data_raw.append(float(message_split[5]))

    data, timestamps, types = remove_anomalies(data_raw, timestamps_raw, types_raw)

    lock_duration_max = float(max(data)) if data else None
    graph_file_name = graph_output_path / f"{LOCK_DURATION_GRAPH_FILE_NAME}{IMAGE_EXTENSION}"
    data_file_name = graph_output_path / f"{LOCK_DURATION_GRAPH_FILE_NAME}.json"
    mean_values, types_with_color, type_colors = plot_graph(
        data, types, timestamps, LOCK_DURATION, TIMESTAMP, f"{LOCK_DURATION} (minutes)", graph_file_name, lock_duration_max
    )
    save_graph_data(data_file_name, data, types, timestamps, mean_values)
    return data, types_with_color, type_colors, mean_values, data_file_name, graph_file_name


def create_builds_waiting_in_queue_graph(
    messages: list[str], graph_output_path: Path
) -> tuple[list[int], list[str], dict[str, str], dict[str, float], Path, Path]:
    data_raw, types_raw, timestamps_raw = [], [], []

    for message in messages:
        if LOCK_DURATION not in message and AVAILABLE_MACHINES not in message:
            message_split = message.split("\n")
            timestamps_raw.append(message_split[1])
            types_raw.append(message_split[0])
            data_raw.append(int(message_split[3]))

    data, timestamps, types = remove_anomalies(data_raw, timestamps_raw, types_raw)

    graph_file_name = graph_output_path / f"{BUILDS_WAITING_IN_QUEUE_GRAPH_FILE_NAME}{IMAGE_EXTENSION}"
    data_file_name = graph_output_path / f"{BUILDS_WAITING_IN_QUEUE_GRAPH_FILE_NAME}.json"
    mean_values, types_with_color, type_colors = plot_graph(
        data, types, timestamps, BUILD_IN_QUEUE, TIMESTAMP, BUILD_IN_QUEUE, graph_file_name
    )
    save_graph_data(data_file_name, data, types, timestamps, mean_values)
    return data, types_with_color, type_colors, mean_values, data_file_name, graph_file_name


def create_available_machines_graph(
    messages: list[str], graph_output_path: Path
) -> tuple[list[int], list[str], dict[str, str], dict[str, float], Path, Path]:
    data_raw, types_raw, timestamps_raw = [], [], []  # Available machines

    for message in messages:
        if AVAILABLE_MACHINES in message and JOB_ID in message:
            message_split = message.split("\n")
            timestamps_raw.append(message_split[1])
            types_raw.append(message_split[0])
            data_raw.append(int(message_split[4]))
    data, timestamps, types = remove_anomalies(data_raw, timestamps_raw, types_raw)

    graph_file_name = graph_output_path / f"{AVAILABLE_MACHINES_GRAPH_FILE_NAME}{IMAGE_EXTENSION}"
    data_file_name = graph_output_path / f"{AVAILABLE_MACHINES_GRAPH_FILE_NAME}.json"
    mean_values, types_with_color, type_colors = plot_graph(
        data, types, timestamps, AVAILABLE_MACHINES, TIMESTAMP, AVAILABLE_MACHINES, graph_file_name
    )
    save_graph_data(data_file_name, data, types, timestamps, mean_values)
    return data, types_with_color, type_colors, mean_values, data_file_name, graph_file_name


if __name__ == "__main__":
    # Importing here to prevent cyclic imports.
    from Tests.scripts.build_machines_report import WAIT_IN_LINE_CHANNEL_ID, WAIT_IN_LINE_SLACK_MESSAGES_FILE_NAME  # noqa: E402

    parser = argparse.ArgumentParser(
        description="Script to generate a machines statistics report from the wait in line slack channel."
    )
    parser.add_argument(
        "-t",
        "--test-data",
        required=False,
        action="store_true",
        help="Use test data and don't connect to Slack to fetch the messages.",
    )
    options = parser.parse_args()
    if options.test_data:
        with open(WAIT_IN_LINE_SLACK_MESSAGES_FILE_NAME) as f:
            slack_messages = json.load(f)
    else:
        client = WebClient(token=os.environ["SLACK_TOKEN"])
        slack_messages = get_messages_from_slack(client, WAIT_IN_LINE_CHANNEL_ID)
        with open(WAIT_IN_LINE_SLACK_MESSAGES_FILE_NAME, "w") as f:
            f.write(json.dumps(slack_messages, indent=4, default=str, sort_keys=True))
    output_path = Path(".")
    create_lock_duration_graph(slack_messages, output_path)
    create_available_machines_graph(slack_messages, output_path)
    create_builds_waiting_in_queue_graph(slack_messages, output_path)
