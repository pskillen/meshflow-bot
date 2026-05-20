"""Resolve the running meshflow-bot version string for API reporting.

Production images set ``APP_VERSION`` from the Docker ``VERSION`` build arg (see Dockerfile).
Local runs without that env var default to ``development``, matching meshflow-api settings.
"""

from __future__ import annotations

import os

_DEFAULT_VERSION = "development"


def get_bot_version() -> str:
    """Return the bot version to report on connect (max 128 chars)."""
    version = os.environ.get("APP_VERSION", _DEFAULT_VERSION).strip()
    if not version:
        version = _DEFAULT_VERSION
    return version[:128]
