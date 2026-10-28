from __future__ import annotations

import hmac
from pathlib import Path

from contract import ConnectInput, ConnectOutput
from plugin.sources import (
    CONNECTION_PREFIX,
    TemporarilyUnavailable,
    connections,
    credential_refs,
    is_set,
    keys,
    resolve,
    source,
)

# workspace -> the sources whose connect already failed once this run
FAILED: dict[Path, set[str]] = {}


def refusal(source_id: str, ref: str, listed: list[str]) -> PermissionError:
    """Why a source refuses a ref it does not accept. A listed ref is revoked when set and retired when not."""
    if ref in listed and is_set(ref):
        return PermissionError(f"{source_id} rejects the key {ref} names: that key was revoked")
    if ref in listed:
        return PermissionError(
            f"{source_id} no longer accepts {ref}: it was retired for this source, so setting it would not unblock it"
        )
    if is_set(ref):
        return PermissionError(f"{source_id} rejects the key {ref} names")
    return PermissionError(f"{source_id} does not accept {ref}: it is not listed for this source")


def connect(given: ConnectInput, workspace: Path) -> ConnectOutput:
    """Open a connection to a fixture source with the key a credential ref names. The mock API expects the key
    its own credential ref names; a wrong, revoked, retired or unset one raises, naming refs only. A source marked
    flaky_connect fails its first connect of the run, whatever the ref, then connects."""
    row = source(given.source_id)
    if given.credential_ref not in credential_refs():
        resolve(given.credential_ref)  # raises without echoing it: it may be a key value pasted in by mistake
    failed = FAILED.setdefault(workspace.resolve(), set())
    if row.get("flaky_connect") and row["id"] not in failed:
        failed.add(row["id"])
        raise TemporarilyUnavailable(
            f"{row['id']} is temporarily unavailable (HTTP 503); call connect again with the same arguments"
        )
    if given.credential_ref != row["credential_ref"]:
        raise refusal(row["id"], given.credential_ref, row["listed_refs"])
    presented = resolve(given.credential_ref)
    if not hmac.compare_digest(presented.encode("utf-8"), keys()[row["credential_ref"]].encode("utf-8")):
        raise PermissionError(f"{row['id']} rejects the key {given.credential_ref} names")
    opened = connections(workspace)
    connection_id = f"{CONNECTION_PREFIX}{len(opened) + 1}"
    opened[connection_id] = given.source_id
    return ConnectOutput(connection_id=connection_id, source_id=given.source_id, credential_ref=given.credential_ref)
