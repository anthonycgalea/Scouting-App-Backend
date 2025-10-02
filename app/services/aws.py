"""AWS service utilities for lazy S3 client creation."""

from __future__ import annotations

import os
from typing import Optional

import boto3
from botocore.client import BaseClient


_S3_CLIENT: Optional[BaseClient] = None
_TEAM_IMAGES_BUCKET: Optional[str] = None


class MissingEnvironmentVariableError(RuntimeError):
    """Raised when a required AWS environment variable is missing."""

    def __init__(self, variable_name: str) -> None:
        super().__init__(
            f"Environment variable '{variable_name}' is required for AWS S3 access but was not set."
        )
        self.variable_name = variable_name


def _get_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise MissingEnvironmentVariableError(name)
    return value


def get_s3_client() -> BaseClient:
    """Return a cached boto3 S3 client configured from environment variables."""
    global _S3_CLIENT

    if _S3_CLIENT is None:
        _S3_CLIENT = boto3.client(
            "s3",
            aws_access_key_id=_get_env_var("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=_get_env_var("AWS_SECRET_ACCESS_KEY"),
            region_name=_get_env_var("AWS_DEFAULT_REGION"),
        )

    return _S3_CLIENT


def get_team_images_bucket() -> str:
    """Return the cached S3 bucket name for team images."""
    global _TEAM_IMAGES_BUCKET

    if _TEAM_IMAGES_BUCKET is None:
        _TEAM_IMAGES_BUCKET = _get_env_var("TEAM_IMAGES_BUCKET")

    return _TEAM_IMAGES_BUCKET
