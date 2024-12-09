import argparse
import json
from pathlib import Path

from jinja2 import Template


def main():
    arg_parser = argparse.ArgumentParser(description="Will convert the cve report generated to html")
    arg_parser.add_argument(
        "--json_report",
        required=True,
        help="Path to the json file report",
    )
    arg_parser.add_argument("--output_path", help="Path to output the html file", default="cve_report.html")
    args = arg_parser.parse_args()
    path = Path(__file__).absolute()

    with open(path.parent / "cve_report_jinja_template.html") as f:
        template_text = f.read()
    with open(args.json_report) as f:
        final_text = Template(template_text).render(res=json.load(f))
    with open(args.output_path, "w") as f:
        f.write(final_text)
    print(f"saved html file at {args.output_path}")


if __name__ == "__main__":
    main()
