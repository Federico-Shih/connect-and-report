from __future__ import annotations

from pathlib import Path

from slimconfig import build_output

from contract import FetchRecordsInput, FetchRecordsOutput, Record
from plugin.engine import page
from plugin.sources import PAGE_SIZE, TemporarilyUnavailable, connections, source

# workspace -> the (source id, cursor) pages that already failed once this run
FAILED: dict[Path, set[tuple[str, str | None]]] = {}


def fetch_records(given: FetchRecordsInput, workspace: Path) -> FetchRecordsOutput:
    """One page of the connected source's records, as the source serves them (a record may come again on the next
    page). An unknown connection raises; a flaky page fails the first time it is asked for, then serves."""
    opened = connections(workspace)
    if given.connection_id not in opened:
        raise ValueError(f"unknown connection: {given.connection_id!r}; call connect first and pass its connection_id")
    row = source(opened[given.connection_id])
    records, next_cursor = page(row["records"], given.cursor, PAGE_SIZE)
    failed = FAILED.setdefault(workspace.resolve(), set())
    if given.cursor in row.get("flaky_cursors", []) and (row["id"], given.cursor) not in failed:
        failed.add((row["id"], given.cursor))
        raise TemporarilyUnavailable(
            f"{row['id']} is temporarily unavailable (HTTP 503); call fetch_records again with the same cursor"
        )
    return FetchRecordsOutput(
        source_id=row["id"],
        required_fields=list(row["required_fields"]),
        records=[build_output(record, Record) for record in records],
        next_cursor=next_cursor,
    )
