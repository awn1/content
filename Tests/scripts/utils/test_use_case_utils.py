import ast
import json
from pathlib import Path

DEPENDENCIES_KEY = "additional_needed_packs"


class TestUseCaseDataExtractor:
    def extract_config(self, file_path: str) -> dict:
        """
        Extracting the pack dependencies packs from a test use case file.
        The data is found as json in the file in the following format:
        {
        "marketplaces": ["XSIAM"],
        "additional_needed_packs":
            {"PackOne": "instance_name1",
            "PackTwo": ""
            }
        }
        """
        with open(file_path) as f:
            file_content = f.read()
        parsed_ast = ast.parse(file_content)

        if not parsed_ast:
            raise ValueError("Failed to parse test use case. Make sure the file exists.")

        # Get the module-level docstring
        try:
            docstr = ast.get_docstring(parsed_ast) if parsed_ast else ""

            config = json.loads(docstr) if docstr else {}

        except Exception as e:
            raise ValueError(
                "Test Use Case's configuration could not be parsed. Verify the docstring contain valid json format."
                ""
                f"Error: {e!s}"
            )

        return config

    def get_additional_packs_data(self, file_path: str | Path) -> list[dict[str, str]]:
        """Extracting the additional packs needed to be installed from a given Use Case

        Args:
            file_path (str | Path): the test use case path

        Returns:
            list: List of dependencies packs to install.
        """
        config = self.extract_config(str(file_path))
        packs = config.get("additional_needed_packs", {})
        return list(packs.keys())

    @staticmethod
    def get_test_use_case_path(test_use_case_name, pack):
        p = Path("Packs", pack, "TestUseCases", f"{test_use_case_name}.py")

        return p
