import ast
import json
from pathlib import Path

DEPENDENCIES_KEY = "additional_needed_packs"


class FlowDataExtractor:
    def extract_config(self, file_path: str) -> dict:
        """
        Extracting the pack dependencies packs from a flow test file.
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
            raise ValueError("Failed to parse flow test. Make sure the file exists.")

        # Get the module-level docstring
        try:
            docstr = ast.get_docstring(parsed_ast) if parsed_ast else ""

            if not docstr:
                raise ValueError("Failed to parse docstring for configuration. Verify the docstring contain valid json format.")
            config = json.loads(docstr) if docstr else {}

        except Exception as e:
            raise ValueError(
                "Flow Test's configuration could not be parsed. Verify the docstring contain valid json format." f"Error: {e!s}"
            )

        return config

    def get_additional_packs_data(self, file_path: str | Path) -> list[dict[str, str]]:
        """Extracting the additional packs needed to be installed from a given Flow Test

        Args:
            file_path (str | Path): the flow test path

        Returns:
            list: List of dependencies packs to install.
        """
        config = self.extract_config(str(file_path))
        packs = config.get("additional_needed_packs", {})
        return list(packs.keys())

    def get_playbook_flow_test_path(self, playbook_flow_test_name, pack):
        p = Path("Packs", pack, "PlaybookFlowTests", f"{playbook_flow_test_name}.py")

        return p
