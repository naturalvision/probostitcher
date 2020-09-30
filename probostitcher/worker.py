from probostitcher import Specs

import boto3
import os


QUEUE_NAME = os.environ["PROBOSTITCHER_QUEUE_NAME"]
QUEUE_REGION = os.environ["PROBOSTITCHER_QUEUE_REGION"]


def get_queue():
    sqs = boto3.resource("sqs", region_name=QUEUE_REGION)
    return sqs.get_queue_by_name(QueueName=QUEUE_NAME)


def main():
    while True:
        process_messages()


def process_messages():
    queue = get_queue()
    for message in queue.receive_messages(WaitTimeSeconds=10):
        print("Received message")
        try:
            specs = Specs(filecontents=message.body)
            print("Created specs object")
            specs.upload()
        except Exception as e:
            print(e)
        message.delete()


if __name__ == "__main__":
    main()
