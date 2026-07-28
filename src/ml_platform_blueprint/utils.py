"""Small, dependency-free utilities shared by platform components."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_RESOURCE_NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")


class InvalidResourceName(ValueError):
    """Raised when a tenant or model name is unsafe for storage or Kubernetes."""


def utc_now() -> str:
    """Return an RFC 3339 timestamp with second precision."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_resource_name(value: str, field: str = "resource") -> str:
    """Validate a DNS-label-compatible name used in paths and database keys."""

    if not _RESOURCE_NAME.fullmatch(value):
        raise InvalidResourceName(
            f"{field} must be a lower-case DNS label (1-63 characters); got {value!r}"
        )
    return value


def canonical_json(value: Any) -> str:
    """Serialize data in a stable representation suitable for hashing."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically replace a text file without exposing partial artifacts."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise
