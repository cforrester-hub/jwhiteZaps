"""DigitalOcean Spaces client for file storage."""

import logging
from datetime import datetime
from typing import Optional
from io import BytesIO

import boto3
from botocore.exceptions import ClientError

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize S3 client for DigitalOcean Spaces
_client = None


def get_spaces_client():
    """Get or create the Spaces client."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            region_name=settings.spaces_region,
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=settings.spaces_access_key,
            aws_secret_access_key=settings.spaces_secret_key,
        )
    return _client


def upload_file(
    file_content: bytes,
    filename: str,
    folder: str = "",
    content_type: str = "application/octet-stream",
    public: bool = True,
) -> dict:
    """
    Upload a file to DigitalOcean Spaces.

    Args:
        file_content: The file bytes to upload
        filename: The filename (will be sanitized)
        folder: Optional folder path (e.g., "recordings/2024/01")
        content_type: MIME type of the file
        public: Whether to make the file publicly readable

    Returns:
        dict with key, url, and size
    """
    client = get_spaces_client()

    # Build the object key
    if folder:
        key = f"{folder.strip('/')}/{filename}"
    else:
        key = filename

    # Set ACL based on public flag
    extra_args = {"ContentType": content_type}
    if public:
        extra_args["ACL"] = "public-read"

    try:
        client.put_object(
            Bucket=settings.spaces_bucket,
            Key=key,
            Body=file_content,
            **extra_args,
        )

        public_url = f"{settings.public_base_url}/{key}"

        logger.info(f"Uploaded file: {key} ({len(file_content)} bytes)")
        return {
            "key": key,
            "url": public_url,
            "size": len(file_content),
            "content_type": content_type,
        }

    except ClientError as e:
        logger.error(f"Failed to upload file: {e}")
        raise


def download_file(key: str) -> bytes:
    """
    Download a file from DigitalOcean Spaces.

    Args:
        key: The object key

    Returns:
        File content as bytes
    """
    client = get_spaces_client()

    try:
        response = client.get_object(Bucket=settings.spaces_bucket, Key=key)
        return response["Body"].read()
    except ClientError as e:
        logger.error(f"Failed to download file: {e}")
        raise


def delete_file(key: str) -> bool:
    """
    Delete a file from DigitalOcean Spaces.

    Args:
        key: The object key

    Returns:
        True if deleted successfully
    """
    client = get_spaces_client()

    try:
        client.delete_object(Bucket=settings.spaces_bucket, Key=key)
        logger.info(f"Deleted file: {key}")
        return True
    except ClientError as e:
        logger.error(f"Failed to delete file: {e}")
        raise


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    """
    Generate a presigned URL for temporary access.

    Args:
        key: The object key
        expires_in: URL expiration time in seconds (default 1 hour)

    Returns:
        Presigned URL string
    """
    client = get_spaces_client()

    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.spaces_bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except ClientError as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        raise


def list_files(prefix: str = "", max_keys: int = 1000) -> list:
    """
    List files in a folder/prefix.

    Args:
        prefix: Filter by key prefix (folder path)
        max_keys: Maximum number of results

    Returns:
        List of file info dicts
    """
    client = get_spaces_client()

    try:
        response = client.list_objects_v2(
            Bucket=settings.spaces_bucket,
            Prefix=prefix,
            MaxKeys=max_keys,
        )

        files = []
        for obj in response.get("Contents", []):
            files.append(
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "url": f"{settings.public_base_url}/{obj['Key']}",
                }
            )
        return files

    except ClientError as e:
        logger.error(f"Failed to list files: {e}")
        raise


def file_exists(key: str) -> bool:
    """Check if a file exists."""
    client = get_spaces_client()

    try:
        client.head_object(Bucket=settings.spaces_bucket, Key=key)
        return True
    except ClientError:
        return False
