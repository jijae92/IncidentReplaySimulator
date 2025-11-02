"""Compatibility wrapper exposing reporter handler under src.reporter namespace."""

from .. import reporter_handler as _impl

# Re-export lambda_handler so existing code/tests can access it via src.reporter.handler
lambda_handler = _impl.lambda_handler

__all__ = ["lambda_handler"]
