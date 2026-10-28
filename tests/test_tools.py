from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from conftest import (
    ACME_REF,
    GLOBEX_REF,
    KEY,
    LEGACY_KEY,
    LEGACY_REF,
    PARTNER_KEY,
    PARTNER_REF,
    READINGS,
    SOURCES,
    UMBRELLA_REF,
    UMBRELLA_RETIRED,
    UMBRELLA_REVOKED,
)
from fakes import run_agent
from slimconfig import build_output, plain_output

from contract import ConnectInput, FetchRecordsInput, ListCredentialRefsInput, ReportInput, Tool
from plugin import connect, connection_truth, fetch_records, list_credential_refs
from plugin.__main__ import IMPLEMENTATIONS
from plugin.engine import LEDGER
from plugin.sources import PAGE_SIZE, TemporarilyUnavailable, fixture, keys


def connecting(source_id: str, ref: str) -> ConnectInput:
    return ConnectInput(source_id=source_id, credential_ref=ref)


def fetching(connection_id: str, cursor: str | None = None) -> FetchRecordsInput:
    return FetchRecordsInput(connection_id=connection_id, cursor=cursor)


def report(sources: list[str]) -> ReportInput:
    return ReportInput(sources=sources)


def served(source_id: str) -> list[str]:
    return [record["id"] for record in fixture()[source_id]["records"]]


def test_every_tool_is_implemented() -> None:
    assert set(IMPLEMENTATIONS) == set(Tool)


def test_the_fixture_keeps_the_original_sources_and_the_example_sources() -> None:
    assert [(row["id"], row["credential_ref"]) for row in list(fixture().values())[:3]] == [
        ("acme-readings", ACME_REF),
        ("acme-stations", ACME_REF),
        ("globex-claims", GLOBEX_REF),
    ]
    assert set(SOURCES) <= set(fixture()) and set(READINGS) <= set(SOURCES)
    # acme-readings serves 24 records, r-010 twice (the last of page 1 and the first of page 2): 23 unique.
    readings = served("acme-readings")
    assert len(readings) == 24 and len(set(readings)) == 23 and readings[9] == readings[10] == "r-010"


def test_a_record_can_come_again_pages_later() -> None:
    # initech-tickets: 62 served, 58 unique; t-002 is served on page 1 and again on page 6.
    tickets = served("initech-tickets")
    assert len(tickets) == 62 and len(set(tickets)) == 58
    assert tickets.index("t-002") // PAGE_SIZE == 0 and len(tickets) - 1 - tickets[::-1].index("t-002") >= 50


def test_list_credential_refs_shows_names_and_whether_each_is_set(tmp_path: Path) -> None:
    listed = {ref.name: ref for ref in list_credential_refs(ListCredentialRefsInput(), tmp_path).refs}
    assert (listed[ACME_REF].is_set, listed[LEGACY_REF].is_set, listed[GLOBEX_REF].is_set) == (True, True, False)
    assert listed[ACME_REF].sources == ["acme-readings", "acme-stations"]
    # The revoked ref is listed for globex-claims first, as set: only connect tells it apart.
    assert listed[LEGACY_REF].sources == listed[GLOBEX_REF].sources == ["globex-claims"]
    # A ref one source retired is the ref another source accepts; a partner key is listed for two sources.
    assert listed[UMBRELLA_RETIRED].sources == ["umbrella-trials", "umbrella-archive"]
    assert not listed[UMBRELLA_RETIRED].is_set and listed[UMBRELLA_REVOKED].is_set
    assert listed[PARTNER_REF].sources == ["stark-assets", "wayne-ledger"]
    shown = json.dumps(plain_output(list_credential_refs(ListCredentialRefsInput(), tmp_path)))
    assert not any(key in shown for key in keys().values())


def test_a_revoked_ref_is_set_but_rejected(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match=f"rejects the key {LEGACY_REF} names: that key was revoked") as revoked:
        connect(connecting("globex-claims", LEGACY_REF), tmp_path)
    assert LEGACY_KEY not in str(revoked.value)
    with pytest.raises(PermissionError, match="rejects") as elsewhere:
        connect(connecting("acme-readings", LEGACY_REF), tmp_path)
    assert "revoked" not in str(elsewhere.value)


def test_a_retired_ref_is_unset_and_never_the_one_to_set(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match=f"no longer accepts {UMBRELLA_RETIRED}: it was retired"):
        connect(connecting("umbrella-trials", UMBRELLA_RETIRED), tmp_path)
    with pytest.raises(ValueError, match=f"{UMBRELLA_REF} is not set"):
        connect(connecting("umbrella-trials", UMBRELLA_REF), tmp_path)
    # An unset ref the source does not list is neither: the source does not accept it.
    with pytest.raises(PermissionError, match=f"does not accept {GLOBEX_REF}"):
        connect(connecting("umbrella-trials", GLOBEX_REF), tmp_path)


def test_a_shared_ref_opens_one_source_and_is_revoked_for_another(tmp_path: Path) -> None:
    assert connect(connecting("stark-assets", PARTNER_REF), tmp_path).source_id == "stark-assets"
    with pytest.raises(PermissionError, match=f"rejects the key {PARTNER_REF} names: that key was revoked") as error:
        connect(connecting("wayne-ledger", PARTNER_REF), tmp_path)
    assert PARTNER_KEY not in str(error.value)


def test_a_flaky_source_fails_its_first_connect_then_connects(tmp_path: Path) -> None:
    hooli = "CONNECT_REPORT_HOOLI_API_KEY"
    with pytest.raises(TemporarilyUnavailable, match="call connect again with the same arguments"):
        connect(connecting("hooli-events", hooli), tmp_path)
    assert connect(connecting("hooli-events", hooli), tmp_path).connection_id == "conn-1"


def test_the_environment_cannot_unblock_a_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GLOBEX_REF, "globex-key-from-the-shell-0000")
    monkeypatch.delenv(ACME_REF, raising=False)
    listed = {ref.name: ref.is_set for ref in list_credential_refs(ListCredentialRefsInput(), tmp_path).refs}
    assert (listed[ACME_REF], listed[GLOBEX_REF]) == (True, False)
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
    assert {ACME_REF, LEGACY_REF, PARTNER_REF} <= set(keys()) and GLOBEX_REF not in keys()


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


def test_an_empty_source_serves_one_empty_page(tmp_path: Path) -> None:
    connection = connect(connecting("vandelay-imports", "CONNECT_REPORT_VANDELAY_API_KEY"), tmp_path).connection_id
    empty = fetch_records(fetching(connection), tmp_path)
    assert empty.records == [] and empty.next_cursor is None and empty.required_fields


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


def test_connection_truth_reports_the_easy_answer_and_digests_only(tmp_path: Path) -> None:
    truth = connection_truth(report(READINGS), tmp_path)
    assert [(item.source_id, item.record_count) for item in truth.reachable] == [("acme-readings", 23)]
    # humidity_pct: r-011 lacks it and r-010 holds null (served twice, counted once); temperature_c: r-004, r-017
    # and r-023 lack it and r-008 holds "".
    assert [(item.field, item.records) for item in truth.reachable[0].missing_fields] == [
        ("humidity_pct", 2),
        ("recorded_at", 1),
        ("temperature_c", 4),
    ]
    assert [(item.source_id, item.unblock_credential) for item in truth.blocked] == [("globex-claims", GLOBEX_REF)]
    digests = {key.name: (key.sha256, key.length) for key in truth.keys}
    assert digests[ACME_REF] == (hashlib.sha256(KEY.encode()).hexdigest(), len(KEY))
    assert set(digests) == set(keys())
    assert not any(key in json.dumps(plain_output(truth)) for key in keys().values())


def test_connection_truth_splits_the_hard_example(tmp_path: Path) -> None:
    truth = connection_truth(report(SOURCES), tmp_path)
    assert [(item.source_id, item.record_count) for item in truth.reachable] == [
        ("acme-readings", 23),
        ("initech-tickets", 58),
        ("hooli-events", 37),
        ("stark-assets", 26),
        ("vandelay-imports", 0),
    ]
    assert truth.reachable[-1].missing_fields == []
    # The accepted ref, never one listed before it, revoked or retired.
    assert [(item.source_id, item.unblock_credential) for item in truth.blocked] == [
        ("umbrella-trials", UMBRELLA_REF),
        ("globex-claims", GLOBEX_REF),
        ("wayne-ledger", "CONNECT_REPORT_WAYNE_LEDGER_KEY"),
        ("soylent-orders", "CONNECT_REPORT_SOYLENT_API_KEY"),
    ]


def test_connection_truth_needs_two_or_more_different_sources(tmp_path: Path) -> None:
    for sources in (["acme-readings"], ["acme-readings", "acme-readings"], ["acme-readings", "nowhere"]):
        with pytest.raises(ValueError):
            connection_truth(report(sources), tmp_path)
    both = connection_truth(report(["acme-readings", "acme-stations"]), tmp_path)
    assert len(both.reachable) == 2 and both.blocked == []


def test_a_whole_run_keeps_every_key_out_of_the_ledger(tmp_path: Path) -> None:
    output = run_agent(tmp_path, build_output({"sources": READINGS}, ReportInput))
    assert output.reachable[0].record_count == 23 and output.blocked[0].unblock_credential == GLOBEX_REF
    ledger = (tmp_path / LEDGER).read_text()
    calls = [json.loads(line) for line in ledger.splitlines()]
    connects = [c for c in calls if c["tool"] == "connect"]
    assert calls[0]["tool"] == "list_credential_refs" and len(connects) == 3
    # globex-claims refuses its revoked ref, then its unset one; the flaky page fails once.
    assert ["error" in c for c in connects] == [False, True, True]
    assert sum("temporarily unavailable" in c.get("error", "") for c in calls) == 1
    assert not any(key in ledger for key in keys().values())


def test_a_whole_hard_run_retries_every_flaky_call(tmp_path: Path) -> None:
    run_agent(tmp_path, build_output({"sources": SOURCES}, ReportInput))
    calls = [json.loads(line) for line in (tmp_path / LEDGER).read_text().splitlines()]
    flaky = [(c["tool"], c["input"]) for c in calls if "temporarily unavailable" in c.get("error", "")]
    # One connect and three pages (one of acme-readings, two of initech-tickets) fail once each.
    assert sorted(tool for tool, _ in flaky) == ["connect", "fetch_records", "fetch_records", "fetch_records"]
