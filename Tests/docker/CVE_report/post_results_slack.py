import argparse
import json

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def get_message_for_results(results, artifact_host, ci_job_id):
    message = f"""<{artifact_host}/{ci_job_id}/artifacts/cve_report.html|New CVE report available>
Number of latest images that need attention: {results.get('num_problematic_candidates')}
Number of content items that have {', '.join(results.get('relevant_levels'))} cves: {results.get('total_cve_content_items')}
Number of content items that have critical cves: {results.get('total_critical_cve_content_items')}
"""
    if any(e for e in results.get("new_cve_data").values() if e["cve_updated_info"]):
        message += """
:alert: <!channel> New critical cves in our content were published :alert:

"""

        for cve_id, cve_details in [
            (cve_id, cve_details)
            for cve_id, cve_details in results.get("new_cve_data").items()
            if cve_details["cve_updated_info"]
        ]:
            message += f'- CVE ID: `{cve_id}` CVSS: `{cve_details["cve_details"]["CVS_score"]}` Num content affected: `{cve_details["num_content_affected"]}` Date Published: `{cve_details["cve_details"]["published"]}` <{cve_details["cve_details"]["vulnerability_link"]}|Vulnerability link> \n Update Details: {cve_details["cve_updated_info"]}\n\n'
        message += "\nFor more details see the above report"
    return message


def post_to_slack(results, slack_token, channel, host, job_id):
    message = get_message_for_results(results, host, job_id)
    slack_client = WebClient(token=slack_token)
    try:
        response = slack_client.chat_postMessage(channel=channel, text=message)
        assert response["message"]["text"]
        print("Message posted successfully")
    except SlackApiError as e:
        print(f"Error posting message to Slack: {e.response['error']}")


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("-t", "--token", help="Slack Token", required=True)
    arg_parser.add_argument("-r", "--results", help="Results json file", required=True)
    arg_parser.add_argument(
        "-jid",
        "--ci_job_id",
        help="The job id the artifact was created in",
        required=True,
    )
    arg_parser.add_argument("-ah", "--artifact_host", help="The host of the artifact", required=True)
    arg_parser.add_argument("-c", "--channel", help="Channel to post results to", required=True)
    args = arg_parser.parse_args()
    with open(args.results) as f:
        results = json.load(f)
        post_to_slack(results, args.token, args.channel, args.artifact_host, args.ci_job_id)


if __name__ == "__main__":
    main()
