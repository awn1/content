import argparse
import json
import os
import sys


def get_test_data_folders(machine_assignment, chosen_machine):
    with open(machine_assignment) as file:
        data = json.load(file)
        test_use_cases = data.get(chosen_machine, {}).get("tests", {}).get("TestUseCases", [])
        test_data_folders = []
        for test_case_path in test_use_cases:
            test_data_folder = os.path.join(os.path.dirname(test_case_path), "test_data")
            if os.path.exists(test_data_folder):
                test_data_folders.append(test_data_folder)
        return test_data_folders


def option_handler():
    parser = argparse.ArgumentParser(description="Collecting alert data to push to xsiam.")
    parser.add_argument("-ma", "--machine_assignment", help="Machine assignment file path", required=True)
    parser.add_argument("-sm", "--selected_machine", help="Current selected machine", required=True)

    options = parser.parse_args()

    return options


def main():
    options = option_handler()
    print(get_test_data_folders(options.machine_assignment, options.selected_machine), file=sys.stdout)


if __name__ == "__main__":
    main()
