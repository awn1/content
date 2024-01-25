import os
from time import sleep

import matplotlib.pyplot as plt


import matplotlib.dates as mdates

from datetime import datetime

from matplotlib.ticker import MultipleLocator
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

slack_token = os.getenv("SLACK_TOKEN")
channel_id = 'C06DQRKJLMU'

client = WebClient(token=slack_token)
colors_dict = {"content-locks/locks-xsiam-ga": 'red', "content-locks/locks-xsoar-ng": 'blue',
               "content-locks/locks-xsoar-ng-nightly": 'green', "content-locks/locks-xsiam-ga-nightly": 'orange',
               "content-locks/locks-xsiam-ga-upload": 'purple'}
colors_dict2 = {"content-locks/locks-xsiam-ga": 'xsiam-ga', "content-locks/locks-xsoar-ng": 'xsoar-ng',
                "content-locks/locks-xsoar-ng-nightly": 'xsoar-ng-nightly',
                "content-locks/locks-xsiam-ga-nightly": 'xsiam-ga-nightly',
                "content-locks/locks-xsiam-ga-upload": 'xsiam-ga-upload'}

def create_graphs(messages):
    durations1, types1, timestamps1 = [], [], []
    locks2, types2, timestamps2 = [], [], []
    machines3, types3, timestamps3 = [], [], []

    for message in messages:
        if "has joined the channel" in message:
            continue
        if "Lock Duration" in message:
            match_dict1 = message.split("\n")
            durations1.append(float(match_dict1[5]))
            types1.append(colors_dict.get(match_dict1[2]))
            timestamps1.append(match_dict1[1])
        elif "Available machines" in message:
            match_dict3 = message.split("\n")
            if "4377685" in match_dict3[2] or "4377570" in match_dict3[2] or "4377569" in match_dict3[2]:
                continue
            machines3.append(int(match_dict3[4]))
            types3.append(colors_dict.get(match_dict3[0]))
            timestamps3.append(match_dict3[1])
        else:
            match_dict2 = message.split("\n")
            types2.append(colors_dict.get(match_dict2[0]))
            timestamps2.append(match_dict2[1])
            locks2.append(int(match_dict2[3]))

    import pytz

    ist = pytz.timezone('Israel')

    timestamps2 = [datetime.strptime(item, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=pytz.utc).astimezone(ist) for item in timestamps2]
    plt.legend(
        handles=[
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=color, markersize=6, label=colors_dict2[type_])
            for
            type_, color in colors_dict.items()],
        loc='upper center', bbox_to_anchor=(0.5, 1.1), ncol=len(colors_dict),
        fontsize=7, handlelength=3, handletextpad=1, borderaxespad=0.5)

    plt.scatter(timestamps2, locks2, c=types2, label=types2)
    plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=1))  # Adjust the interval as needed
    plt.gca().yaxis.set_major_locator(MultipleLocator(1))  # Adjust the interval as needed

    plt.gcf().autofmt_xdate()
    plt.xlabel('Timestamp')
    plt.ylabel('Number of builds in queue')
    plt.tight_layout()
    plt.xticks(fontsize=6)
    plt.savefig('plot2.png')

    plt.show()

    timestamps1 = [datetime.strptime(item, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=pytz.utc).astimezone(ist) for item in timestamps1]

    plt.legend(
        handles=[
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=color, markersize=6, label=colors_dict2[type_])
            for
            type_, color in colors_dict.items()],
        loc='upper center', bbox_to_anchor=(0.5, 1.1), ncol=len(colors_dict),
        fontsize=7, handlelength=3, handletextpad=1, borderaxespad=0.5)

    plt.scatter(timestamps1, durations1, c=types1, label=types1)
    plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=1))  # Adjust the interval as needed
    plt.xticks(fontsize=6)  # Adjust the fontsize value as needed

    plt.gcf().autofmt_xdate()

    plt.xlabel('Timestamp')
    plt.ylabel('Lock Duration (minutes)')
    plt.tight_layout()
    plt.savefig('plot1.png')

    plt.show()



    timestamps3 = [datetime.strptime(item, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=pytz.utc).astimezone(ist) for item in timestamps3]

    plt.legend(
        handles=[
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=color, markersize=6, label=colors_dict2[type_])
            for
            type_, color in colors_dict.items()],
        loc='upper center', bbox_to_anchor=(0.5, 1.1), ncol=len(colors_dict),
        fontsize=7, handlelength=3, handletextpad=1, borderaxespad=0.5)

    plt.scatter(timestamps3, machines3, c=types3, label=types3)
    plt.gca().xaxis.set_major_locator(mdates.MinuteLocator(interval=120))  # Adjust the interval as needed
    plt.xticks(fontsize=6)  # Adjust the fontsize value as needed
    plt.gca().yaxis.set_major_locator(MultipleLocator(1))  # Adjust the interval as needed

    plt.gcf().autofmt_xdate()

    plt.xlabel('Timestamp')
    plt.ylabel('Number of available machines')
    plt.tight_layout()
    plt.savefig('plot3.png')

    plt.show()

def get_messages_from_slack(channel_id):
    messages = []
    # oldest = ""
    try:
        result = client.conversations_history(
            channel=channel_id,
            # oldest='1705316166',
            limit=1000)
        messages += [message['text'] for message in result['messages']]
        while result['has_more']:
            sleep(1)  # need to wait 1 sec before next call due to rate limits
            result = client.conversations_history(
                channel=channel_id,
                cursor=result['response_metadata']['next_cursor'],
                limit=1000
            )
            messages += [message['text'] for message in result['messages']]
        return messages
    except SlackApiError as e:
        print("Error while fetching the conversation history")


slack_messages = get_messages_from_slack(channel_id)
create_graphs(slack_messages)
