from __future__ import annotations

from pathlib import Path

from contract import CredentialRef, ListCredentialRefsInput, ListCredentialRefsOutput
from plugin.sources import credential_refs, is_set


def list_credential_refs(given: ListCredentialRefsInput, workspace: Path) -> ListCredentialRefsOutput:
    """Every credential ref by name, whether it is set, and which sources it opens; never a value."""
    return ListCredentialRefsOutput(
        refs=[CredentialRef(name=name, is_set=is_set(name), sources=ids) for name, ids in credential_refs().items()]
    )
