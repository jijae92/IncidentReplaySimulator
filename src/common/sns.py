"""Compatibility module exposing SNS client under src.common namespace."""

from ..sns import SnsClient  # noqa: F401

__all__ = ["SnsClient"]
