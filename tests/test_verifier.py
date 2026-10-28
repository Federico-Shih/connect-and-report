from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ACME_REF, GLOBEX_REF, KEY, LEGACY_KEY, LEGACY_REF
from fakes import run_agent
from slimconfig import build_output, plain_output

import verifier
from contract import (
    ConnectInput,
    ConnectionTruthOutput,
    ConnectOutput,
    FetchRecordsInput,
    FetchRecordsOutput,
    ListCredentialRefsInput,
    ListCredentialRefsOutput,
    ReportInput,
    ReportOutput,
)
from plugin import connect, connection_truth, fetch_records, list_credential_refs
from plugin.__main__ import run_call
from plugin.engine import LEDGER
from plugin.sources import CONNECTION_PREFIX, MIN_KEY_LENGTH, PAGE_SIZE
from verifier import checks

TASK = "connect-and-report"
CHECKS = [
    "reference",
    "reference-digests",
    "task-input",
    "report-submitted",
    "no-key-leaked",
    "sources",
    "record-count",
    "missing-fields-well-formed",
    "missing-fields-exact",
    "unblock-credential",
]
OUTCOME = CHECKS[5:]
# 24 records served over 3 pages, r-010 twice: 23 records; page 2 fails once. 3 required fields have gaps, 2 of them
# held as null or "".
READINGS = ["acme-readings", "globex-claims"]
STATIONS = ["acme-stations", "globex-claims"]  # 7 records, none missing a required field
MISSING = [
    {"field": "humidity_pct", "records": 2},
    {"field": "recorded_at", "records": 1},
    {"field": "temperature_c", "records": 4},
]
EXACT = {
    "reachable_source": "acme-readings",
    "record_count": 23,
    "missing_fields": MISSING,
    "blocked_source": "globex-claims",
    "unblock_credential": GLOBEX_REF,
    "summary": "acme-readings holds 23 records; set the Globex credential to unblock globex-claims.",
}


# The verifier gets contract instances, as NanoAgent's sandbox builds them from JSON.
def task(sources: list[str]) -> ReportInput:
    return build_output({"sources": sources}, ReportInput)


def truth(given: ReportInput, scratch: Path) -> ConnectionTruthOutput:
    return build_output(plain_output(connection_truth(given, scratch)), ConnectionTruthOutput)


def submitted(**changes) -> ReportOutput:
    return build_output({**EXACT, **changes}, ReportOutput)


def judge(workspace: Path, output: ReportOutput | None, sources: list[str] = READINGS, reference=True) -> dict:
    given = task(sources)
    pinned = truth(given, workspace / "scratch") if reference is True else reference
    verdict = verifier.verify_task(TASK, given, output, pinned, str(workspace))
    # The scoring policy's invariant, checked on every verdict: score 1.0 exactly when valid.
    assert (verdict["score"] == 1.0) is verdict["valid"]
    # The verdict's shape, also on every verdict: every check in order, each entry with the same keys; the message
    # names the first failing check and how many more fail.
    entries = verdict["details"]["checks"]
    assert [entry["id"] for entry in entries] == CHECKS
    for entry in entries:
        assert set(entry) == {"id", "constraint", "ok", "expected", "actual", "message"}
        assert (entry["message"] == "") is (entry["ok"] is True)
        assert (entry["ok"] is None) is entry["message"].startswith("Not checked: ")
    failed = [entry for entry in entries if entry["ok"] is False]
    if failed:
        more = f" (+{len(failed) - 1} more)" if len(failed) > 1 else ""
        assert verdict["message"] == f"{failed[0]['id']}: {failed[0]['message']}{more}"
    assert bool(failed) is not verdict["valid"]
    return verdict


def status(verdict: dict) -> dict:
    return {entry["id"]: entry["ok"] for entry in verdict["details"]["checks"]}


def test_the_verifier_mirrors_the_plugin_constants() -> None:
    assert (checks.PAGE_SIZE, checks.MIN_KEY_LENGTH, checks.CONNECTION_PREFIX) == (
        PAGE_SIZE,
        MIN_KEY_LENGTH,
        CONNECTION_PREFIX,
    )


# Correct
def test_approves_an_exact_report_from_a_whole_run(tmp_path: Path) -> None:
    verdict = judge(tmp_path, run_agent(tmp_path, task(READINGS)))
    assert verdict["valid"] is True and verdict["score"] == 1.0 and verdict["details"]["record_count"] == 23


def test_the_order_of_missing_fields_does_not_matter(tmp_path: Path) -> None:
    assert judge(tmp_path, submitted(missing_fields=MISSING[::-1]))["valid"] is True


# Wrong: each of the four parts is all or nothing, so one wrong part scores 0.75.
@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"record_count": 22}, id="count off by one"),
        pytest.param({"record_count": 10}, id="count of the first page only"),
        pytest.param({"missing_fields": MISSING[1:]}, id="a missing field omitted"),
        pytest.param({"missing_fields": [*MISSING, {"field": "station", "records": 1}]}, id="an extra missing field"),
        pytest.param({"missing_fields": [*MISSING[:2], {"field": "temperature_c", "records": 3}]}, id="a wrong count"),
        pytest.param({"unblock_credential": LEGACY_REF}, id="the revoked ref listed first"),
        pytest.param({"missing_fields": [*MISSING, {"field": "note", "records": 17}]}, id="an optional field"),
        pytest.param({"unblock_credential": ACME_REF}, id="the reachable source's ref"),
        pytest.param({"unblock_credential": "GLOBEX_API_KEY"}, id="a near-miss ref name"),
        pytest.param({"unblock_credential": GLOBEX_REF.lower()}, id="the ref name in lower case"),
        pytest.param({"reachable_source": "globex-claims", "blocked_source": "acme-readings"}, id="sources swapped"),
    ],
)
def test_refuses_a_wrong_part(tmp_path: Path, changes: dict) -> None:
    verdict = judge(tmp_path, submitted(**changes))
    assert verdict["valid"] is False and verdict["score"] == 0.75
    assert sum(verdict["details"]["parts"].values()) == 3


def test_a_leaked_key_scores_zero_however_right_the_report(tmp_path: Path) -> None:
    for changes in ({"unblock_credential": KEY}, {"summary": KEY}, {"summary": f"used key={KEY}; it worked"}):
        verdict = judge(tmp_path, submitted(**changes))
        assert verdict["valid"] is False and verdict["score"] == 0.0
        assert verdict["details"]["leaks"] == [f"{ACME_REF} in the output"] and KEY not in str(verdict)
        # A leaked report is not judged further: its strings may hold the key.
        assert status(verdict)["no-key-leaked"] is False and {status(verdict)[name] for name in OUTCOME} == {None}


def test_a_revoked_key_is_a_key_too(tmp_path: Path) -> None:
    verdict = judge(tmp_path, submitted(summary=f"the old key {LEGACY_KEY} is revoked"))
    assert verdict["score"] == 0.0 and verdict["details"]["leaks"] == [f"{LEGACY_REF} in the output"]


# Wrong: the traps the sources set
@pytest.mark.parametrize(
    ("mistake", "wrong"),
    [
        pytest.param({"first_ref_only": True}, ["unblock_credential"], id="reports the revoked ref listed first"),
        pytest.param({"count_served": True}, ["missing_fields", "record_count"], id="counts a re-served record twice"),
        pytest.param({"absent_only": True}, ["missing_fields"], id="counts null and empty as held"),
        pytest.param({"no_retry": True}, ["missing_fields", "record_count"], id="gives up on the failed page"),
    ],
)
def test_each_trap_costs_its_parts(tmp_path: Path, mistake: dict, wrong: list) -> None:
    verdict = judge(tmp_path, run_agent(tmp_path, task(READINGS), **mistake))
    assert verdict["valid"] is False
    assert sorted(part for part, right in verdict["details"]["parts"].items() if not right) == wrong


def test_a_key_in_a_missing_field_name_is_a_leak(tmp_path: Path) -> None:
    leaked = submitted(missing_fields=[*MISSING, {"field": f"x{KEY}x", "records": 1}])
    assert judge(tmp_path, leaked)["score"] == 0.0


def test_a_key_in_a_workspace_file_is_a_leak(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(READINGS))
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "report.md").write_text(f"# Report\nThe Acme key is {KEY}.\n")
    verdict = judge(tmp_path, output)
    assert verdict["valid"] is False and verdict["score"] == 0.0
    assert verdict["details"]["leaks"] == [f"{ACME_REF} in notes/report.md"]


def test_a_key_pasted_as_a_ref_leaks_into_the_ledger(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(READINGS))
    with pytest.raises(ValueError, match="unknown credential ref"):
        run_call("connect", {"source_id": "acme-readings", "credential_ref": KEY}, tmp_path)
    verdict = judge(tmp_path, output)
    assert verdict["score"] == 0.0 and verdict["details"]["leaks"] == [f"{ACME_REF} in {LEDGER.as_posix()}"]


# Missing
def test_refuses_a_task_without_a_reference(tmp_path: Path) -> None:
    verdict = judge(tmp_path, submitted(), reference=None)
    assert verdict["valid"] is False and verdict["score"] == 0.0 and "reference" in verdict["message"]
    assert status(verdict)["task-input"] is None and status(verdict)["sources"] is None


def test_a_reference_for_other_sources_scores_zero(tmp_path: Path) -> None:
    pinned = truth(task(STATIONS), tmp_path / "scratch")
    verdict = judge(tmp_path, submitted(), reference=pinned)
    assert verdict["score"] == 0.0 and verdict["message"].startswith("task-input: ")


def test_refuses_no_report(tmp_path: Path) -> None:
    assert judge(tmp_path, None)["score"] == 0.0


def test_an_empty_report_scores_zero(tmp_path: Path) -> None:
    empty = submitted(reachable_source="", record_count=0, missing_fields=[], blocked_source="", unblock_credential="")
    verdict = judge(tmp_path, empty)
    assert verdict["valid"] is False and verdict["score"] == 0.0


def test_stopping_after_the_first_page_misses_records_and_gaps(tmp_path: Path) -> None:
    verdict = judge(tmp_path, run_agent(tmp_path, task(READINGS), pages=1))
    assert verdict["valid"] is False and verdict["score"] == 0.5
    assert verdict["message"].startswith("record-count: ") and verdict["message"].endswith(" (+1 more)")
    assert verdict["details"]["parts"]["record_count"] is False and verdict["details"]["parts"]["missing_fields"] is False


# Malformed
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        pytest.param({"missing_fields": [*MISSING, MISSING[0]]}, "more than once", id="a field named twice"),
        pytest.param({"missing_fields": [*MISSING, {"field": "station", "records": 0}]}, "records < 1", id="zero"),
        pytest.param({"unblock_credential": f"export {GLOBEX_REF}=..."}, "not a ref name", id="not a name"),
        pytest.param({"record_count": -23}, "record_count -23", id="negative count"),
    ],
)
def test_refuses_a_malformed_report(tmp_path: Path, changes: dict, message: str) -> None:
    verdict = judge(tmp_path, submitted(**changes))
    assert verdict["valid"] is False and message in verdict["message"] and verdict["score"] == 0.75
    if "missing_fields" in changes:
        assert status(verdict)["missing-fields-exact"] is None


def test_refuses_a_malformed_reference(tmp_path: Path) -> None:
    given = task(READINGS)
    plain = plain_output(truth(given, tmp_path / "scratch"))
    for key in ({**plain["keys"][0], "sha256": "not-a-digest"}, {**plain["keys"][0], "length": 3}):
        broken = build_output({**plain, "keys": [key]}, ConnectionTruthOutput)
        verdict = judge(tmp_path, submitted(), reference=broken)
        assert verdict["valid"] is False and verdict["score"] == 0.0 and "malformed" in verdict["message"]


# Boundary
def test_zero_missing_fields_needs_an_empty_list(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(STATIONS))
    assert output.missing_fields == [] and output.record_count == 7
    assert judge(tmp_path, output, STATIONS)["valid"] is True
    stations = {**plain_output(output), "missing_fields": [{"field": "lat", "records": 1}]}
    assert judge(tmp_path, build_output(stations, ReportOutput), STATIONS)["valid"] is False


def test_a_variable_in_the_environment_leaves_the_source_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(GLOBEX_REF, "globex-key-from-the-shell-0000")
    output = run_agent(tmp_path, task(READINGS))
    assert output.unblock_credential == GLOBEX_REF
    verdict = judge(tmp_path, output)
    assert verdict["valid"] is True
    assert [key.name for key in truth(task(READINGS), tmp_path / "scratch").keys] == [ACME_REF, LEGACY_REF]


def test_only_a_whole_key_is_a_leak(tmp_path: Path) -> None:
    # Each string and file is searched on its own for the key's exact bytes. A key split across two strings, or
    # broken by a character, is not found: the agent never sees a key, so it can only echo one whole.
    half = len(KEY) // 2
    for changes in (
        {"summary": KEY[:-1]},
        {"summary": f"{KEY[:half]} {KEY[half:]}"},
        {"summary": KEY[:half], "unblock_credential": KEY[half:]},
    ):
        assert judge(tmp_path, submitted(**changes))["details"].get("leaks") is None


def test_a_key_in_a_binary_file_is_found(tmp_path: Path) -> None:
    (tmp_path / "dump.bin").write_bytes(b"\xff\xfe\x00" + KEY.encode() + b"\x80")
    assert judge(tmp_path, submitted())["details"]["leaks"] == [f"{ACME_REF} in dump.bin"]


# Tools
def test_list_credential_refs_checks(tmp_path: Path) -> None:
    given = ListCredentialRefsInput()
    made = build_output(plain_output(list_credential_refs(given, tmp_path)), ListCredentialRefsOutput)
    assert verifier.verify_input("list_credential_refs", given)["valid"] is True
    assert verifier.verify_output("list_credential_refs", given, made, str(tmp_path))["valid"] is True
    pasted = build_output({"refs": [{"name": KEY, "is_set": True, "sources": ["acme-readings"]}]}, ListCredentialRefsOutput)
    assert verifier.verify_output("list_credential_refs", given, pasted, str(tmp_path))["valid"] is False


def test_connect_checks(tmp_path: Path) -> None:
    given = build_output({"source_id": "acme-readings", "credential_ref": ACME_REF}, ConnectInput)
    made = build_output(plain_output(connect(given, tmp_path)), ConnectOutput)
    assert verifier.verify_input("connect", given)["valid"] is True
    assert verifier.verify_output("connect", given, made, str(tmp_path))["valid"] is True
    pasted = build_output({"source_id": "acme-readings", "credential_ref": KEY}, ConnectInput)
    assert verifier.verify_input("connect", pasted)["valid"] is False
    other = build_output({"source_id": "acme-stations", "credential_ref": ACME_REF}, ConnectInput)
    assert verifier.verify_output("connect", other, made, str(tmp_path))["valid"] is False


def test_fetch_records_checks(tmp_path: Path) -> None:
    connection = connect(ConnectInput(source_id="acme-readings", credential_ref=ACME_REF), tmp_path).connection_id
    given = build_output({"connection_id": connection, "cursor": None}, FetchRecordsInput)
    made = build_output(plain_output(fetch_records(given, tmp_path)), FetchRecordsOutput)
    assert verifier.verify_input("fetch_records", given)["valid"] is True
    assert verifier.verify_output("fetch_records", given, made, str(tmp_path))["valid"] is True
    assert verifier.verify_input("fetch_records", FetchRecordsInput(connection_id="acme", cursor=None))["valid"] is False
    later = build_output({"connection_id": connection, "cursor": "cursor-20"}, FetchRecordsInput)
    assert verifier.verify_output("fetch_records", later, made, str(tmp_path))["valid"] is False


def test_connection_truth_checks(tmp_path: Path) -> None:
    given = task(READINGS)
    made = truth(given, tmp_path)
    assert verifier.verify_input("connection_truth", given)["valid"] is True
    assert verifier.verify_output("connection_truth", given, made, str(tmp_path))["valid"] is True
    assert verifier.verify_input("connection_truth", task(["acme-readings"]))["valid"] is False
    overcounted = build_output({**plain_output(made), "record_count": 2}, ConnectionTruthOutput)
    assert verifier.verify_output("connection_truth", given, overcounted, str(tmp_path))["valid"] is False
    assert verifier.verify_output("connection_truth", task(STATIONS), made, str(tmp_path))["valid"] is False
