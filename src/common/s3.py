"""Compatibility module exposing S3 client under src.common namespace."""

from ..s3 import S3Client  # noqa: F401

__all__ = ["S3Client"]
