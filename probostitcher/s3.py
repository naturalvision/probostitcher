from botocore.config import Config
from botocore.exceptions import ClientError
from urllib.parse import urlparse

import boto3
import logging
import os


REGION = os.environ["PROBOSTITCHER_REGION"]


def get_boto_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://s3.{REGION}.amazonaws.com",
        config=Config(signature_version="s3v4", region_name=REGION),
    )


def create_presigned_url(url: str, expiration: int = 3600) -> str:
    """Generate a presigned URL to share an S3 object"""
    parsed_url = urlparse(url)
    try:
        response = get_boto_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": parsed_url.netloc,
                "Key": parsed_url.path[1:],
            },
            ExpiresIn=expiration,
        )
    except ClientError as e:
        logging.error(e)
        raise
    # The response contains the presigned URL
    return response


def exists(object_key: str) -> bool:
    try:
        get_boto_client().head_object(
            Bucket=os.environ["PROBOSTITCHER_OUTPUT_BUCKET"], Key=object_key
        )
    except ClientError:
        return False
    return True
