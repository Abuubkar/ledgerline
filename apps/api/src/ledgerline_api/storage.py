"""Uploaded PDFs in S3-compatible storage. boto3 is synchronous, so async callers wrap these in asyncio.to_thread.

Only the S3 API is used, so the backend (SeaweedFS locally, see ADR 0008) is a configuration choice.
"""

from functools import cache

import boto3
from botocore.config import Config

from ledgerline_api.settings import settings


@cache
def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",  # required by botocore; ignored by S3-compatible servers
        # Retries belong to the job queue, not to each S3 call.
        config=Config(retries={"max_attempts": 1}, connect_timeout=5, read_timeout=30),
    )


def uri(key: str) -> str:
    return f"s3://{settings.s3_bucket}/{key}"


def put(key: str, content: bytes) -> str:
    _client().put_object(Bucket=settings.s3_bucket, Key=key, Body=content, ContentType="application/pdf")
    return uri(key)


def get(file_uri: str) -> bytes:
    bucket, _, key = file_uri.removeprefix("s3://").partition("/")
    return _client().get_object(Bucket=bucket, Key=key)["Body"].read()


def delete(file_uri: str) -> None:
    bucket, _, key = file_uri.removeprefix("s3://").partition("/")
    _client().delete_object(Bucket=bucket, Key=key)
