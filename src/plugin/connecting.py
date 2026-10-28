from __future__ import annotations

import hmac
from pathlib import Path

from contract import ConnectInput, ConnectOutput
from plugin.sources import CONNECTION_PREFIX, connections, keys, resolve, source


def connect(given: ConnectInput, workspace: Path) -> ConnectOutput:
    """Open a connection to a fixture source with the key a credential ref names. The mock API expects the key
    its own credential ref names; a wrong, revoked, unset or empty one raises, naming refs only."""
    row = source(given.source_id)
    presented = resolve(given.credential_ref)
    expected = keys().get(row["credential_ref"], "")
    if not expected or not hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8")):
        if given.credential_ref in row["listed_refs"]:
            raise PermissionError(
                f"{given.source_id} rejects the key {given.credential_ref} names: that key was revoked"
            )
        raise PermissionError(f"{given.source_id} rejects the key {given.credential_ref} names")
    opened = connections(workspace)
    connection_id = f"{CONNECTION_PREFIX}{len(opened) + 1}"
    opened[connection_id] = given.source_id
    return ConnectOutput(connection_id=connection_id, source_id=given.source_id, credential_ref=given.credential_ref)
