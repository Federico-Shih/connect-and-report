from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from conftest import ACME_REF, GLOBEX_REF, KEY, LEGACY_KEY, LEGACY_REF
from fakes import run_agent
from slimconfig import build_output, plain_output

from contract import ConnectInput, FetchRecordsInput, ListCredentialRefsInput, ReportInput, Tool
from plugin import connect, connection_truth, fetch_records, list_credential_refs
from plugin.__main__ import IMPLEMENTATIONS
from plugin.engine import LEDGER
from plugin.fetching import TemporarilyUnavailable
from plugin.sources import PAGE_SIZE, fixture, keys

READINGS = ["acme-readings", "globex-claims"]


def connecting(source_id: str, ref: str) -> ConnectInput:
    return ConnectInput(source_id=source_id, credential_ref=ref)


def fetching(connection_id: str, cursor: str | None = None) -> FetchRecordsInput:
    return FetchRecordsInput(connection_id=connection_id, cursor=cursor)


def report(sources: list[str]) -> ReportInput:
    return ReportInput(sources=sources)


def test_every_tool_is_implemented() -> None:
    assert set(IMPLEMENTATIONS) == set(Tool)


def test_the_fixture_holds_two_acme_sources_and_one_globex_source() -> None:
    assert [(row["id"], row["credential_ref"]) for row in fixture().values()] == [
        ("acme-readings", ACME_REF),
        ("acme-stations", ACME_REF),
        ("globex-claims", GLOBEX_REF),
    ]
    # acme-readings serves 24 records, r-010 twice (the last of page 1 and the first of page 2): 23 unique.
    served = [record["id"] for record in fixture()["acme-readings"]["records"]]
    assert len(served) == 24 and len(set(served)) == 23 and served[9] == served[10] == "r-010"


def test_list_credential_refs_shows_names_and_whether_each_is_set(tmp_path: Path) -> None:
    listed = list_credential_refs(ListCredentialRefsInput(), tmp_path)
    assert [(ref.name, ref.is_set) for ref in listed.refs] == [(ACME_REF, True), (LEGACY_REF, True), (GLOBEX_REF, False)]
    assert listed.refs[0].sources == ["acme-readings", "acme-stations"]
    # The revoked ref is listed for globex-claims first, as set: only connect tells it apart.
    assert listed.refs[1].sources == listed.refs[2].sources == ["globex-claims"]
    shown = json.dumps(plain_output(listed))
    assert KEY not in shown and LEGACY_KEY not in shown


def test_a_revoked_ref_is_set_but_rejected(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match=f"rejects the key {LEGACY_REF} names: that key was revoked") as revoked:
        connect(connecting("globex-claims", LEGACY_REF), tmp_path)
    assert LEGACY_KEY not in str(revoked.value)
    with pytest.raises(PermissionError, match="rejects") as elsewhere:
        connect(connecting("acme-readings", LEGACY_REF), tmp_path)
    assert "revoked" not in str(elsewhere.value)


def test_the_environment_cannot_unblock_a_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GLOBEX_REF, "globex-key-from-the-shell-0000")
    monkeypatch.delenv(ACME_REF, raising=False)
    listed = list_credential_refs(ListCredentialRefsInput(), tmp_path).refs
    assert [ref.is_set for ref in listed] == [True, True, False]
    with pytest.raises(ValueError, match=f"{GLOBEX_REF} is not set"):
        connect(connecting("globex-claims", GLOBEX_REF), tmp_path)
    assert connect(connecting("acme-readings", ACME_REF), tmp_path).connection_id == "conn-1"


def test_connect_opens_the_reachable_source_with_its_ref(tmp_path: Path) -> None:
    opened = connect(connecting("acme-readings", ACME_REF), tmp_path)
    assert (opened.connection_id, opened.source_id, opened.credential_ref) == ("conn-1", "acme-readings", ACME_REF)
    assert connect(connecting("acme-stations", ACME_REF), tmp_path).connection_id == "conn-2"


def test_connect_refuses_a_blocked_source_naming_its_ref_only(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=f"{GLOBEX_REF} is not set") as blocked:
        connect(connecting("globex-claims", GLOBEX_REF), tmp_path)
    assert KEY not in str(blocked.value)
    with pytest.raises(PermissionError, match="rejects") as wrong_ref:
        connect(connecting("globex-claims", ACME_REF), tmp_path)
    assert KEY not in str(wrong_ref.value)


def test_connect_refuses_an_unknown_source_or_ref_without_echoing_it(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown source id"):
        connect(connecting("initech-hr", ACME_REF), tmp_path)
    with pytest.raises(ValueError, match="unknown credential ref") as pasted:
        connect(connecting("acme-readings", KEY), tmp_path)
    assert KEY not in str(pasted.value)


def test_every_bundled_key_is_at_least_16_characters() -> None:
    # The verifier's leak hunt refuses shorter keys: one could turn up in ordinary text by chance.
    assert keys() and all(len(key.encode("utf-8")) >= 16 for key in keys().values())
    assert set(keys()) == {ACME_REF, LEGACY_REF}


def test_fetch_records_pages_through_the_connected_source(tmp_path: Path) -> None:
    connection = connect(connecting("acme-readings", ACME_REF), tmp_path).connection_id
    first = fetch_records(fetching(connection), tmp_path)
    assert len(first.records) == PAGE_SIZE and first.next_cursor == "cursor-10"
    assert first.required_fields == ["station", "recorded_at", "temperature_c", "humidity_pct"]
    assert first.records[3].id == "r-004" and "temperature_c" not in first.records[3].fields
    # Held but empty: r-008's temperature is "", r-010's humidity null.
    assert first.records[7].fields["temperature_c"] == "" and first.records[9].fields["humidity_pct"] is None
    last = fetch_records(fetching(connection, "cursor-20"), tmp_path)
    assert [record.id for record in last.records] == ["r-020", "r-021", "r-022", "r-023"] and last.next_cursor is None


def test_a_flaky_page_fails_once_then_serves_and_repeats_a_record(tmp_path: Path) -> None:
    connection = connect(connecting("acme-readings", ACME_REF), tmp_path).connection_id
    with pytest.raises(TemporarilyUnavailable, match="call fetch_records again with the same cursor"):
        fetch_records(fetching(connection, "cursor-10"), tmp_path)
    second = fetch_records(fetching(connection, "cursor-10"), tmp_path)
    assert second.records[0].id == "r-010" and second.next_cursor == "cursor-20"
    # It fails once per run, even on a new connection.
    again = connect(connecting("acme-readings", ACME_REF), tmp_path).connection_id
    assert fetch_records(fetching(again, "cursor-10"), tmp_path).records[0].id == "r-010"


def test_fetch_records_needs_an_open_connection_and_a_known_cursor(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown connection"):
        fetch_records(fetching("conn-1"), tmp_path)
    connection = connect(connecting("acme-stations", ACME_REF), tmp_path).connection_id
    with pytest.raises(ValueError, match="unknown cursor"):
        fetch_records(fetching(connection, "cursor-10"), tmp_path)


def test_connection_truth_reports_the_answer_and_digests_only(tmp_path: Path) -> None:
    truth = connection_truth(report(READINGS), tmp_path)
    assert (truth.reachable_source, truth.record_count, truth.blocked_source, truth.unblock_credential) == (
        "acme-readings",
        23,
        "globex-claims",
        GLOBEX_REF,
    )
    # humidity_pct: r-011 lacks it and r-010 holds null (served twice, counted once); temperature_c: r-004, r-017
    # and r-023 lack it and r-008 holds "".
    assert [(item.field, item.records) for item in truth.missing_fields] == [
        ("humidity_pct", 2),
        ("recorded_at", 1),
        ("temperature_c", 4),
    ]
    assert [(key.name, key.sha256, key.length) for key in truth.keys] == [
        (ACME_REF, hashlib.sha256(KEY.encode()).hexdigest(), len(KEY)),
        (LEGACY_REF, hashlib.sha256(LEGACY_KEY.encode()).hexdigest(), len(LEGACY_KEY)),
    ]
    assert KEY not in json.dumps(plain_output(truth)) and LEGACY_KEY not in json.dumps(plain_output(truth))
    assert connection_truth(report(["acme-stations", "globex-claims"]), tmp_path).missing_fields == []


def test_connection_truth_needs_exactly_one_reachable_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for sources in (["acme-readings", "acme-stations"], ["acme-readings"], ["acme-readings", "acme-readings"]):
        with pytest.raises(ValueError):
            connection_truth(report(sources), tmp_path)
    monkeypatch.delitem(keys(), ACME_REF)
    with pytest.raises(ValueError, match="exactly one"):
        connection_truth(report(READINGS), tmp_path)


def test_a_whole_run_keeps_every_key_out_of_the_ledger(tmp_path: Path) -> None:
    output = run_agent(tmp_path, build_output({"sources": READINGS}, ReportInput))
    assert output.record_count == 23 and output.unblock_credential == GLOBEX_REF
    ledger = (tmp_path / LEDGER).read_text()
    calls = [json.loads(line) for line in ledger.splitlines()]
    assert [c["tool"] for c in calls][:4] == ["list_credential_refs", "connect", "connect", "connect"]
    # globex-claims refuses its revoked ref, then its unset one; the flaky page fails once.
    assert ["error" in c for c in calls[1:4]] == [False, True, True]
    assert sum("temporarily unavailable" in c.get("error", "") for c in calls) == 1
    assert KEY not in ledger and LEGACY_KEY not in ledger
