"""The bundled fixture sources (fixtures/sources.json), their credential refs, and this run's open connections.

Keys come from the bundled credential store (fixtures/credentials.json), never the environment, so every run is
the same with nothing to set. A ref the store has no key for is blocked. Values never leave this module: only ref
names do.

The sources are not tidy: a source may list a revoked ref next to the one it accepts (a row's listed_refs), serve a
record again on the next page, hold a required field as null or "", and fail a page once before serving it (a row's
flaky_cursors).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from contract import MissingField

FIXTURE = Path(__file__).with_name("fixtures") / "sources.json"
CREDENTIALS = Path(__file__).with_name("fixtures") / "credentials.json"
PAGE_SIZE = 10
# A shorter key would be too easy to "find" in ordinary text when the verifier hunts for leaks; every bundled key
# is at least this long.
MIN_KEY_LENGTH = 16
CONNECTION_PREFIX = "conn-"


@cache
def fixture() -> dict[str, dict[str, Any]]:
    """Every fixture source by id, in fixture order: {id, name, credential_ref (the one ref it accepts),
    listed_refs, required_fields, records (as served, repeats included), and optionally flaky_cursors}."""
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["sources"]
    return {row["id"]: row for row in rows}


def source(source_id: str) -> dict[str, Any]:
    if source_id not in fixture():
        raise ValueError(f"unknown source id: {source_id!r}; known sources: {', '.join(fixture())}")
    return fixture()[source_id]


def credential_refs() -> dict[str, list[str]]:
    """Every credential ref the sources list -> the ids of the sources it is listed for, in fixture order. A listed
    ref is not always one the source accepts: it may be revoked."""
    refs: dict[str, list[str]] = {}
    for row in fixture().values():
        for ref in row["listed_refs"]:
            refs.setdefault(ref, []).append(row["id"])
    return refs


@cache
def keys() -> dict[str, str]:
    """The bundled credential store: credential ref -> key. A ref it lacks is not set."""
    return json.loads(CREDENTIALS.read_text(encoding="utf-8"))["keys"]


def is_set(ref: str) -> bool:
    return bool(keys().get(ref))


def resolve(ref: str) -> str:
    """The key the credential ref names, from the bundled credential store. Raises when it has none; the message
    names the ref, never a value."""
    if ref not in credential_refs():
        # Never echo it: an unknown ref may be a key value pasted in by mistake.
        raise ValueError("unknown credential ref; pass a name list_credential_refs lists, never a key value")
    if not is_set(ref):
        raise ValueError(f"credential ref {ref} is not set: no key is provisioned for it; a person must set it")
    return keys()[ref]


def unique_records(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The source's records, each once: a record served again (the same id) counts once."""
    return list({record["id"]: record for record in row["records"]}.values())


def lacks(record: dict[str, Any], field: str) -> bool:
    """A record lacks a field it does not hold, or holds as null or the empty string."""
    return record["fields"].get(field) in (None, "")


def missing_fields(row: dict[str, Any]) -> list[MissingField]:
    """Each required field some records lack, with how many records lack it, each record counted once."""
    records = unique_records(row)
    counts = {field: sum(lacks(record, field) for record in records) for field in row["required_fields"]}
    return [MissingField(field=field, records=count) for field, count in sorted(counts.items()) if count]


# workspace -> connection id -> source id. One plugin process lasts the whole run, so connections survive calls.
CONNECTIONS: dict[Path, dict[str, str]] = {}


def connections(workspace: Path) -> dict[str, str]:
    return CONNECTIONS.setdefault(workspace.resolve(), {})
