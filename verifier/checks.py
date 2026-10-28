"""Checks shared by the tool verifiers. Pure functions of their arguments and the files on disk."""

import hashlib
import re
from dataclasses import asdict
from pathlib import Path

# These mirror src/plugin (the verifier may import only the standard library and the contract);
# tests/test_verifier.py holds them equal.
PAGE_SIZE = 10
MIN_KEY_LENGTH = 16
CONNECTION_PREFIX = "conn-"
CURSOR = re.compile(r"cursor-(\d+)")
CONNECTION_ID = re.compile(re.escape(CONNECTION_PREFIX) + r"[1-9]\d*")
SOURCE_ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
# A credential ref is an upper-case NAME; a key value (mixed case, dashes, ...) is not one.
CREDENTIAL_REF = re.compile(r"[A-Z_][A-Z0-9_]*")
SHA256 = re.compile(r"[0-9a-f]{64}")


def result(valid, message, *, score=None, **details):
    return {
        "valid": valid,
        "score": float(valid) if score is None else score,
        "message": message,
        "details": details,
    }


def duplicates(items):
    return sorted({item for item in items if items.count(item) > 1})


def digest_problem(keys):
    """Why the reference's key digests cannot be searched for, or None."""
    for key in keys:
        if not SHA256.fullmatch(key.sha256) or key.length < MIN_KEY_LENGTH or not CREDENTIAL_REF.fullmatch(key.name):
            return f"the reference's digest of {key.name!r} is malformed"
    return None


def holds_key(data, key):
    """Whether some run of ``key.length`` bytes in ``data`` hashes to ``key.sha256``: the key, verbatim."""
    return any(
        hashlib.sha256(data[start : start + key.length]).hexdigest() == key.sha256
        for start in range(len(data) - key.length + 1)
    )


def strings(value):
    """Every string inside a plain value (dicts, lists), in order."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    return []


def leaks(output, workspace, keys):
    """Where a key's value appears: "output" (any string of the submitted output) or a workspace file's path.
    Each string and each file is searched on its own, as UTF-8 bytes. Only names are returned, never a value."""
    found = []
    texts = [text.encode("utf-8") for text in strings(asdict(output))]
    root = Path(workspace)
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for key in keys:
        if any(holds_key(text, key) for text in texts):
            found.append(f"{key.name} in the output")
        found += [f"{key.name} in {path.relative_to(root).as_posix()}" for path in files if holds_key(path.read_bytes(), key)]
    return found
