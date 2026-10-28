"""Rebuild src/plugin/fixtures/sources.json and credentials.json: the three original sources as they are, and the
generated ones below. Deterministic (a fixed seed), so a rebuild changes nothing unless this file does.

    uv run python tests/make_fixtures.py

Each generated source sets the traps its comment names. A ref a source lists but does not accept is revoked when
it is set (connect refuses its key) and retired when it is not (connect says the source no longer accepts it).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

FIXTURES = Path(__file__).parents[1] / "src" / "plugin" / "fixtures"
KEEP = ("acme-readings", "acme-stations", "globex-claims")
SEED = 480
P = "CONNECT_REPORT_"
# Absent, null and "": the three ways a record lacks a field.
LACKS = ("absent", None, "")

VALUES = {
    "ticket_id": lambda r, i: f"INC-{7100 + i}",
    "opened_at": lambda r, i: (
        f"2026-09-{1 + i % 28:02d}T{r.randrange(24):02d}:{r.choice(['00', '15', '30', '45'])}:00Z"
    ),
    "status": lambda r, i: r.choice(["open", "pending", "resolved", "closed"]),
    "priority": lambda r, i: r.choice(["P1", "P2", "P3", "P4"]),
    "assignee": lambda r, i: r.choice(["mbolton", "plawrence", "slambert", "jsmykowski", "ntrent"]),
    "queue": lambda r, i: r.choice(["network", "payroll", "facilities", "printers"]),
    "assignee_email": lambda r, i: f"{r.choice(['mbolton', 'plawrence', 'ntrent'])}@initech.example",
    "resolution_note": lambda r, i: r.choice(["rebooted", "replaced toner", "escalated", "duplicate"]),
    "event_id": lambda r, i: f"EV-{300 + i}",
    "venue": lambda r, i: r.choice(["Hall A", "Hall B", "Rooftop", "Auditorium"]),
    "starts_at": lambda r, i: f"2026-11-{1 + i % 30:02d}T{9 + r.randrange(9):02d}:00:00Z",
    "capacity": lambda r, i: str(r.choice([40, 80, 120, 250, 500])),
    "organizer": lambda r, i: r.choice(["gbelson", "rhendricks", "dchugtai", "bgilfoyle"]),
    "venue_notes": lambda r, i: r.choice(["step-free access", "no catering", "AV booked"]),
    "asset_tag": lambda r, i: f"SI-{20400 + i * 7}",
    "model": lambda r, i: r.choice(["Mk II", "Mk III", "Mk V", "Mk VII"]),
    "location": lambda r, i: r.choice(["Malibu", "Queens", "Long Island", "Stark Tower"]),
    "purchased_on": lambda r, i: f"20{r.randrange(18, 26)}-{1 + r.randrange(12):02d}-{1 + r.randrange(28):02d}",
    "warranty_until": lambda r, i: f"20{r.randrange(26, 31)}-{1 + r.randrange(12):02d}-01",
}


def record(rand: random.Random, prefix: str, i: int, fields: list[str], holes: dict[str, object]) -> dict:
    """Record ``i``: every field a value, except each field in ``holes``, which it lacks in that hole's way."""
    values: dict[str, object] = {}
    for field in fields:
        value = VALUES[field](rand, i)
        if field not in holes:
            values[field] = value
        elif holes[field] != "absent":
            values[field] = holes[field]
    return {"id": f"{prefix}-{i:03d}", "fields": values}


def generated(
    rand: random.Random,
    prefix: str,
    count: int,
    required: list[str],
    optional: list[str],
    gaps: dict[str, int],
    repeats: list[tuple[int, int]],
) -> list[dict]:
    """``count`` unique records, as served. ``gaps``: how many records lack each required field, each in one of
    the three ways in turn. An optional field is often lacked, and never counts. ``repeats``: (record index, served
    position) pairs, each serving that record again, unchanged, at that position."""
    holes: dict[int, dict[str, object]] = {i: {} for i in range(1, count + 1)}
    for field, how_many in gaps.items():
        for n, i in enumerate(sorted(rand.sample(range(1, count + 1), how_many))):
            holes[i][field] = LACKS[n % len(LACKS)]
    for field in optional:
        for i in rand.sample(range(1, count + 1), count // 3):
            holes[i][field] = rand.choice(LACKS)
    records = [record(rand, prefix, i, required + optional, holes[i]) for i in range(1, count + 1)]
    served = list(records)
    for index, position in sorted(repeats, key=lambda pair: pair[1]):
        served.insert(position, records[index - 1])
    return served


def sources(rand: random.Random) -> list[dict]:
    initech = ["ticket_id", "opened_at", "status", "priority", "assignee", "queue"]
    hooli = ["event_id", "venue", "starts_at", "capacity", "organizer"]
    stark = ["asset_tag", "model", "location", "purchased_on"]
    return [
        # 58 records served 62 times over 7 pages: one repeat on a page boundary, three pages apart, and two from
        # page 1 on the last page. The ref listed first is revoked. Two pages fail once. assignee_email and
        # resolution_note look required but are not.
        {
            "id": "initech-tickets",
            "name": "Initech: IT help desk tickets",
            "credential_ref": f"{P}INITECH_API_KEY",
            "listed_refs": [f"{P}INITECH_KEY_V1", f"{P}INITECH_API_KEY"],
            "required_fields": initech,
            "flaky_cursors": ["cursor-20", "cursor-50"],
            "records": generated(
                rand,
                "t",
                58,
                initech,
                ["assignee_email", "resolution_note"],
                {"assignee": 7, "priority": 3, "opened_at": 2, "queue": 5},
                [(10, 10), (14, 33), (2, 58), (6, 61)],
            ),
        },
        # Blocked. Its first ref is revoked (set); its second is retired (unset, and never accepted): the ref it
        # accepts, also unset, comes last.
        {
            "id": "umbrella-trials",
            "name": "Umbrella Corp: clinical trial sites",
            "credential_ref": f"{P}UMBRELLA_API_KEY",
            "listed_refs": [f"{P}UMBRELLA_TOKEN", f"{P}UMBRELLA_READONLY_KEY", f"{P}UMBRELLA_API_KEY"],
            "required_fields": ["site_id", "country", "enrolled"],
            "records": [],
        },
        # connect fails once with a 503 before it opens: a source that looks blocked and is not. 37 records served
        # 38 times over 4 pages; venue_notes looks required but is not.
        {
            "id": "hooli-events",
            "name": "Hooli: campus events",
            "credential_ref": f"{P}HOOLI_API_KEY",
            "listed_refs": [f"{P}HOOLI_API_KEY"],
            "required_fields": hooli,
            "flaky_connect": True,
            "records": generated(
                rand, "e", 37, hooli, ["venue_notes"], {"venue": 4, "capacity": 6, "organizer": 1}, [(21, 30)]
            ),
        },
        # Reachable only with its second ref, a partner key shared with wayne-ledger; its own ref, listed first, is
        # retired and unset, so a run that stops at the first unset ref reports it blocked.
        {
            "id": "stark-assets",
            "name": "Stark Industries: equipment register",
            "credential_ref": f"{P}SHARED_PARTNER_KEY",
            "listed_refs": [f"{P}STARK_API_KEY", f"{P}SHARED_PARTNER_KEY"],
            "required_fields": stark,
            "records": generated(rand, "a", 26, stark, ["warranty_until"], {"purchased_on": 3, "model": 2}, []),
        },
        # Blocked. The shared partner key is listed first and set, but revoked here; a retired archive ref is
        # listed between it and the ref it accepts.
        {
            "id": "wayne-ledger",
            "name": "Wayne Enterprises: general ledger",
            "credential_ref": f"{P}WAYNE_LEDGER_KEY",
            "listed_refs": [f"{P}SHARED_PARTNER_KEY", f"{P}WAYNE_ARCHIVE_KEY", f"{P}WAYNE_LEDGER_KEY"],
            "required_fields": ["entry_id", "account", "amount"],
            "records": [],
        },
        # Reachable and empty: one page of no records.
        {
            "id": "vandelay-imports",
            "name": "Vandelay Industries: import shipments",
            "credential_ref": f"{P}VANDELAY_API_KEY",
            "listed_refs": [f"{P}VANDELAY_API_KEY"],
            "required_fields": ["shipment_id", "origin", "declared_value"],
            "records": [],
        },
        # Blocked, plainly: its one ref is not set.
        {
            "id": "soylent-orders",
            "name": "Soylent Corp: wholesale orders",
            "credential_ref": f"{P}SOYLENT_API_KEY",
            "listed_refs": [f"{P}SOYLENT_API_KEY"],
            "required_fields": ["order_id", "customer", "quantity"],
            "records": [],
        },
        # Not in the example: they list refs the task's sources list too, so list_credential_refs names sources
        # the report must leave out. umbrella-archive accepts the ref umbrella-trials retired.
        {
            "id": "umbrella-archive",
            "name": "Umbrella Corp: archived trials",
            "credential_ref": f"{P}UMBRELLA_READONLY_KEY",
            "listed_refs": [f"{P}UMBRELLA_READONLY_KEY"],
            "required_fields": ["site_id", "country"],
            "records": [],
        },
        {
            "id": "initech-archive",
            "name": "Initech: closed tickets archive",
            "credential_ref": f"{P}INITECH_API_KEY",
            "listed_refs": [f"{P}INITECH_API_KEY", f"{P}INITECH_KEY_V1"],
            "required_fields": ["ticket_id", "status"],
            "records": [],
        },
    ]


# The keys the bundled credential store holds; every other listed ref is unset.
KEYS = {
    f"{P}INITECH_API_KEY": "initech-fixture-5c1a90d4e2b7f83c61",
    f"{P}INITECH_KEY_V1": "initech-v1-revoked-0b8e27c4d9f1a6",
    f"{P}UMBRELLA_TOKEN": "umbrella-token-revoked-7e3f05a9c2d8",
    f"{P}HOOLI_API_KEY": "hooli-fixture-a47d1e9036bc5f28",
    f"{P}SHARED_PARTNER_KEY": "partner-fixture-3d9b6f0e81c47a52",
    f"{P}VANDELAY_API_KEY": "vandelay-fixture-e60c2b8f4a17d935",
}


def main() -> None:
    rand = random.Random(SEED)
    path = FIXTURES / "sources.json"
    kept = [row for row in json.loads(path.read_text(encoding="utf-8"))["sources"] if row["id"] in KEEP]
    if [row["id"] for row in kept] != list(KEEP):
        raise SystemExit(f"sources.json must hold {', '.join(KEEP)}")
    path.write_text(json.dumps({"sources": kept + sources(rand)}, indent=1) + "\n", encoding="utf-8")
    store = FIXTURES / "credentials.json"
    held = json.loads(store.read_text(encoding="utf-8"))["keys"]
    store.write_text(json.dumps({"keys": held | KEYS}, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
