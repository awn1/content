import sys

from Tests.scripts.utils import logging_wrapper as logging


class LogAggregator:
    def __init__(self):
        self.logs = []

    def __enter__(self):
        return self

    def add_log(self, log_message):
        self.logs.append(log_message)

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Process logs
        if self.logs:
            logging.critical("\n".join(self.logs))
            sys.exit(1)
        if exc_type is not None:
            logging.critical(f"An exception occurred: {exc_val}")
