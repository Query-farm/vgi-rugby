"""Defensive value conversion shared by the World Rugby and ESPN flatteners."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

import pyarrow as pa

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def mapping(value: Any) -> Mapping[str, Any]:
    """Return ``value`` when it is a mapping, else an empty one."""
    return value if isinstance(value, Mapping) else {}


def sequence(value: Any) -> Sequence[Any]:
    """Return ``value`` when it is a list, else an empty one."""
    return value if isinstance(value, list) else []


def to_int(value: Any) -> int | None:
    """Parse an integer-like value without treating booleans as integers."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() else None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return None


def to_float(value: Any) -> float | None:
    """Parse a finite floating-point value."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def to_bool(value: Any) -> bool | None:
    """Return a real boolean, or null for anything else."""
    return value if isinstance(value, bool) else None


def to_text(value: Any) -> str | None:
    """Return a non-empty string, or null."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def from_millis(value: Any) -> datetime | None:
    """Convert epoch milliseconds into a UTC timestamp."""
    millis = to_int(value)
    if millis is None:
        return None
    try:
        return datetime.fromtimestamp(millis / 1_000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def to_timestamp(value: Any) -> datetime | None:
    """Parse ESPN's ISO-8601 timestamps (``2026-03-14T14:10Z``) into UTC."""
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def to_date(value: Any) -> date | None:
    """Parse a ``YYYY-MM-DD`` label."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def snake_case(name: str) -> str:
    """Convert an upstream camelCase/PascalCase statistic name to snake_case."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def batch_from_rows(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> pa.RecordBatch:
    """Build a record batch in the declared column order."""
    return pa.RecordBatch.from_arrays(
        [pa.array([row.get(value.name) for row in rows], type=value.type) for value in schema],
        schema=schema,
    )
