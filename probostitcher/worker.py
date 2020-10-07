from probostitcher import Specs
from probostitcher.s3 import exists

import boto3
import os


QUEUE_NAME = os.environ["PROBOSTITCHER_QUEUE_NAME"]
QUEUE_REGION = os.environ["PROBOSTITCHER_QUEUE_REGION"]


def get_queue():
    sqs = boto3.resource("sqs", region_name=QUEUE_REGION)
    return sqs.get_queue_by_name(QueueName=QUEUE_NAME)


def main():
    print(f"Processing messages from queue {QUEUE_NAME} in region {QUEUE_REGION}")
    while True:
        process_messages()


def process_messages():
    queue = get_queue()
    for message in queue.receive_messages(WaitTimeSeconds=10):
        print("Received message")
        try:
            specs = Specs(filecontents=message.body, debug=True)
            print(f"Created specs object for {specs.output_filename}")
            if exists(specs.output_filename):
                print(f"{specs.output_filename} already present: skipping")
            else:
                print(f"Rendering and uploading {specs.output_filename}")
                specs.upload()
                print(f"{specs.output_filename} uploaded")
        except Exception as e:
            print(e)
        message.delete()


if __name__ == "__main__":
    main()
