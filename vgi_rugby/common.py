"""Helpers shared by every table function in the catalog."""

from __future__ import annotations

import json

import pyarrow as pa
from vgi.cache_control import CacheControl
from vgi.metadata import FunctionExample
from vgi_rpc.rpc import OutputCollector

from vgi_rugby.fetch import Rows
from vgi_rugby.meta import result_columns_schema
from vgi_rugby.values import batch_from_rows


def emit(rows: Rows, output_schema: pa.Schema, out: OutputCollector) -> None:
    """Emit flattened rows as one batch with the sources' freshness policy."""
    cache = CacheControl(ttl=rows.ttl) if rows.ttl > 0 else None
    out.emit(batch_from_rows(rows.rows, output_schema), cache_control=cache)
    out.finish()


def function_tags(
    *,
    provider: str,
    category: str,
    title: str,
    schema: pa.Schema,
    llm: str,
    md: str,
    examples: list[tuple[str, str]],
) -> dict[str, str]:
    """Discovery tags for one table function."""
    return {
        "provider": provider,
        "vgi.category": category,
        "vgi.title": title,
        "vgi.result_columns_schema": result_columns_schema(schema),
        "vgi.doc_llm": llm,
        "vgi.doc_md": md,
        "vgi.example_queries": json.dumps(
            [{"description": description, "sql": sql} for description, sql in examples]
        ),
    }


def function_examples(tags: dict[str, str]) -> list[FunctionExample]:
    """Expose the documented example queries as the function's SQL examples."""
    return [
        FunctionExample(sql=example["sql"], description=example["description"])
        for example in json.loads(tags["vgi.example_queries"])
    ]
