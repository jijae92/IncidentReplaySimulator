"""Compatibility module exposing project config under src.common namespace."""

from ..config import AppConfig, get_config  # noqa: F401

__all__ = ["AppConfig", "get_config"]
