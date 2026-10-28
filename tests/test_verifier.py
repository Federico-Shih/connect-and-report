from __future__ import annotations

from pathlib import Path

import pytest
from conftest import (
    ACME_REF,
    GLOBEX_REF,
    KEY,
    LEGACY_KEY,
    LEGACY_REF,
    READINGS,
    SOURCES,
    UMBRELLA_REF,
    UMBRELLA_RETIRED,
)
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
    "sources-listed",
    "sources-split",
    "record-counts",
    "missing-fields-well-formed",
    "missing-fields-exact",
    "unblock-credentials",
]
OUTCOME = CHECKS[5:]
STATIONS = ["acme-stations", "globex-claims"]  # 7 records, none missing a required field
# The easy example, by hand: 24 records served over 3 pages, r-010 twice: 23 records; page 2 fails once. 3 required
# fields have gaps, 2 of them held as null or "". Three cells: the count, the missing fields and the credential.
MISSING = [
    {"field": "humidity_pct", "records": 2},
    {"field": "recorded_at", "records": 1},
    {"field": "temperature_c", "records": 4},
]
READING = {"source_id": "acme-readings", "record_count": 23, "missing_fields": MISSING}
GLOBEX = {"source_id": "globex-claims", "unblock_credential": GLOBEX_REF}
EXACT = {
    "reachable": [READING],
    "blocked": [GLOBEX],
    "summary": "acme-readings holds 23 records; set the Globex credential to unblock globex-claims.",
}
ONE_WRONG = round(2 / 3, 4)
# The hard example: 5 reachable sources (2 cells each) and 4 blocked (1 each).
HARD_CELLS = 14


# The verifier gets contract instances, as NanoAgent's sandbox builds them from JSON.
def task(sources: list[str]) -> ReportInput:
    return build_output({"sources": sources}, ReportInput)


def truth(given: ReportInput, scratch: Path) -> ConnectionTruthOutput:
    return build_output(plain_output(connection_truth(given, scratch)), ConnectionTruthOutput)


def submitted(**changes) -> ReportOutput:
    return build_output({**EXACT, **changes}, ReportOutput)


def reading(**changes) -> ReportOutput:
    """The easy report with acme-readings' entry changed."""
    return submitted(reachable=[{**READING, **changes}])


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


def wrong_cells(verdict: dict) -> list[str]:
    return sorted(cell for cell, right in verdict["details"]["cells"].items() if not right)


def test_the_verifier_mirrors_the_plugin_constants() -> None:
    assert (checks.PAGE_SIZE, checks.MIN_KEY_LENGTH, checks.CONNECTION_PREFIX) == (
        PAGE_SIZE,
        MIN_KEY_LENGTH,
        CONNECTION_PREFIX,
    )


# Correct
def test_approves_an_exact_report_from_a_whole_run(tmp_path: Path) -> None:
    verdict = judge(tmp_path, run_agent(tmp_path, task(READINGS)))
    assert verdict["valid"] is True and verdict["score"] == 1.0 and len(verdict["details"]["cells"]) == 3


def test_approves_an_exact_report_of_the_hard_example(tmp_path: Path) -> None:
    verdict = judge(tmp_path, run_agent(tmp_path, task(SOURCES)), SOURCES)
    assert verdict["valid"] is True and len(verdict["details"]["cells"]) == HARD_CELLS
    assert "5 reachable sources holding 144 records; 4 blocked" in verdict["message"]


def test_the_order_of_entries_and_missing_fields_does_not_matter(tmp_path: Path) -> None:
    assert judge(tmp_path, reading(missing_fields=MISSING[::-1]))["valid"] is True
    output = plain_output(run_agent(tmp_path, task(SOURCES)))
    flipped = {**output, "reachable": output["reachable"][::-1], "blocked": output["blocked"][::-1]}
    assert judge(tmp_path, build_output(flipped, ReportOutput), SOURCES)["valid"] is True


# Wrong: each cell is all or nothing and worth the same, so one wrong cell of three scores 2/3.
@pytest.mark.parametrize(
    "output",
    [
        pytest.param(reading(record_count=22), id="count off by one"),
        pytest.param(reading(record_count=10), id="count of the first page only"),
        pytest.param(reading(missing_fields=MISSING[1:]), id="a missing field omitted"),
        pytest.param(reading(missing_fields=[*MISSING, {"field": "station", "records": 1}]), id="an extra field"),
        pytest.param(reading(missing_fields=[*MISSING[:2], {"field": "temperature_c", "records": 3}]), id="a count"),
        pytest.param(reading(missing_fields=[*MISSING, {"field": "note", "records": 17}]), id="an optional field"),
        pytest.param(submitted(blocked=[{**GLOBEX, "unblock_credential": LEGACY_REF}]), id="the revoked ref"),
        pytest.param(submitted(blocked=[{**GLOBEX, "unblock_credential": ACME_REF}]), id="another source's ref"),
        pytest.param(submitted(blocked=[{**GLOBEX, "unblock_credential": "GLOBEX_API_KEY"}]), id="a near-miss name"),
        pytest.param(submitted(blocked=[{**GLOBEX, "unblock_credential": GLOBEX_REF.lower()}]), id="in lower case"),
    ],
)
def test_refuses_a_wrong_cell(tmp_path: Path, output: ReportOutput) -> None:
    verdict = judge(tmp_path, output)
    assert verdict["valid"] is False and verdict["score"] == ONE_WRONG and len(wrong_cells(verdict)) == 1


def test_sources_swapped_lose_every_cell(tmp_path: Path) -> None:
    swapped = submitted(
        reachable=[{"source_id": "globex-claims", "record_count": 12, "missing_fields": []}],
        blocked=[{"source_id": "acme-readings", "unblock_credential": ACME_REF}],
    )
    verdict = judge(tmp_path, swapped)
    assert verdict["score"] == 0.0 and verdict["message"].startswith("sources-split: ")
    assert verdict["details"]["checks"][CHECKS.index("sources-split")]["expected"] == {
        "acme-readings": "reachable",
        "globex-claims": "blocked",
    }


def test_a_leaked_key_scores_zero_however_right_the_report(tmp_path: Path) -> None:
    for output in (
        submitted(blocked=[{**GLOBEX, "unblock_credential": KEY}]),
        submitted(summary=KEY),
        submitted(summary=f"used key={KEY}; it worked"),
    ):
        verdict = judge(tmp_path, output)
        assert verdict["valid"] is False and verdict["score"] == 0.0
        assert verdict["details"]["leaks"] == [f"{ACME_REF} in the output"] and KEY not in str(verdict)
        # A leaked report is not judged further: its strings may hold the key.
        assert status(verdict)["no-key-leaked"] is False and {status(verdict)[name] for name in OUTCOME} == {None}


def test_a_revoked_key_is_a_key_too(tmp_path: Path) -> None:
    verdict = judge(tmp_path, submitted(summary=f"the old key {LEGACY_KEY} is revoked"))
    assert verdict["score"] == 0.0 and verdict["details"]["leaks"] == [f"{LEGACY_REF} in the output"]


# Wrong: the traps the sources set, in the hard example. Each costs only its cells.
@pytest.mark.parametrize(
    ("mistake", "wrong"),
    [
        pytest.param(
            {"first_ref_only": True},
            [
                "globex-claims.unblock_credential",
                "initech-tickets.missing_fields",
                "initech-tickets.record_count",
                "stark-assets.missing_fields",
                "stark-assets.record_count",
                "umbrella-trials.unblock_credential",
                "wayne-ledger.unblock_credential",
            ],
            id="stops at the first listed ref",
        ),
        pytest.param(
            {"first_unset": True},
            ["umbrella-trials.unblock_credential", "wayne-ledger.unblock_credential"],
            id="names the first unset ref, a retired one",
        ),
        pytest.param(
            {"no_connect_retry": True},
            ["hooli-events.missing_fields", "hooli-events.record_count"],
            id="takes a failed connect for a blocked source",
        ),
        pytest.param(
            {"count_served": True},
            [
                "acme-readings.missing_fields",
                "acme-readings.record_count",
                "hooli-events.record_count",
                "initech-tickets.missing_fields",
                "initech-tickets.record_count",
            ],
            id="counts re-served records again",
        ),
        pytest.param(
            {"absent_only": True},
            [
                f"{source}.missing_fields"
                for source in ("acme-readings", "hooli-events", "initech-tickets", "stark-assets")
            ],
            id="counts null and empty as held",
        ),
        pytest.param(
            {"count_optional": True},
            [
                f"{source}.missing_fields"
                for source in ("acme-readings", "hooli-events", "initech-tickets", "stark-assets")
            ],
            id="counts fields that are not required",
        ),
        pytest.param(
            {"no_retry": True},
            [
                "acme-readings.missing_fields",
                "acme-readings.record_count",
                "initech-tickets.missing_fields",
                "initech-tickets.record_count",
            ],
            id="gives up on a failed page",
        ),
    ],
)
def test_each_trap_costs_its_cells(tmp_path: Path, mistake: dict, wrong: list) -> None:
    verdict = judge(tmp_path, run_agent(tmp_path, task(SOURCES), **mistake), SOURCES)
    assert verdict["valid"] is False and wrong_cells(verdict) == wrong
    assert verdict["score"] == round((HARD_CELLS - len(wrong)) / HARD_CELLS, 4)


def test_a_retired_ref_is_named_in_the_message(tmp_path: Path) -> None:
    verdict = judge(tmp_path, run_agent(tmp_path, task(SOURCES), first_unset=True), SOURCES)
    assert verdict["message"].startswith(
        f"unblock-credentials: Wrong unblock_credential: umbrella-trials needs {UMBRELLA_REF}, not {UMBRELLA_RETIRED!r}"
    )


def test_a_key_in_a_missing_field_name_is_a_leak(tmp_path: Path) -> None:
    assert judge(tmp_path, reading(missing_fields=[*MISSING, {"field": f"x{KEY}x", "records": 1}]))["score"] == 0.0


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


# Wrong: the report's list of sources
def test_a_source_left_out_loses_its_cells(tmp_path: Path) -> None:
    output = plain_output(run_agent(tmp_path, task(SOURCES)))
    output["reachable"] = [item for item in output["reachable"] if item["source_id"] != "vandelay-imports"]
    verdict = judge(tmp_path, build_output(output, ReportOutput), SOURCES)
    assert verdict["message"].startswith("sources-listed: The report's sources differ from the task's: omitted ")
    assert wrong_cells(verdict) == ["vandelay-imports.missing_fields", "vandelay-imports.record_count"]
    assert verdict["score"] == round(12 / HARD_CELLS, 4)


def test_a_source_the_task_does_not_name_counts_as_a_wrong_cell(tmp_path: Path) -> None:
    verdict = judge(tmp_path, run_agent(tmp_path, task(SOURCES), every_listed=True), SOURCES)
    listed = verdict["details"]["checks"][CHECKS.index("sources-listed")]
    assert listed["actual"] == {"unknown": ["acme-stations", "initech-archive", "umbrella-archive"]}
    assert wrong_cells(verdict) == [] and verdict["details"]["extra_entries"] == 3
    assert verdict["score"] == round(HARD_CELLS / (HARD_CELLS + 3), 4)


def test_a_source_listed_twice_is_judged_by_its_first_entry(tmp_path: Path) -> None:
    twice = submitted(blocked=[GLOBEX, {"source_id": "acme-readings", "unblock_credential": ACME_REF}])
    verdict = judge(tmp_path, twice)
    assert status(verdict)["sources-listed"] is False and status(verdict)["sources-split"] is True
    assert wrong_cells(verdict) == [] and verdict["score"] == 0.75


# Missing
def test_refuses_a_task_without_a_reference(tmp_path: Path) -> None:
    verdict = judge(tmp_path, submitted(), reference=None)
    assert verdict["valid"] is False and verdict["score"] == 0.0 and "reference" in verdict["message"]
    assert status(verdict)["task-input"] is None and status(verdict)["sources-listed"] is None


def test_a_reference_for_other_sources_scores_zero(tmp_path: Path) -> None:
    pinned = truth(task(STATIONS), tmp_path / "scratch")
    verdict = judge(tmp_path, submitted(), reference=pinned)
    assert verdict["score"] == 0.0 and verdict["message"].startswith("task-input: ")


def test_refuses_no_report(tmp_path: Path) -> None:
    assert judge(tmp_path, None)["score"] == 0.0


def test_an_empty_report_scores_zero(tmp_path: Path) -> None:
    verdict = judge(tmp_path, submitted(reachable=[], blocked=[]))
    assert verdict["valid"] is False and verdict["score"] == 0.0 and len(wrong_cells(verdict)) == 3


def test_stopping_after_the_first_page_misses_records_and_gaps(tmp_path: Path) -> None:
    verdict = judge(tmp_path, run_agent(tmp_path, task(READINGS), pages=1))
    assert verdict["valid"] is False and verdict["score"] == round(1 / 3, 4)
    assert verdict["message"].startswith("record-counts: ") and verdict["message"].endswith(" (+1 more)")
    assert wrong_cells(verdict) == ["acme-readings.missing_fields", "acme-readings.record_count"]


# Malformed
@pytest.mark.parametrize(
    ("output", "message"),
    [
        pytest.param(reading(missing_fields=[*MISSING, MISSING[0]]), "more than once", id="a field named twice"),
        pytest.param(reading(missing_fields=[*MISSING, {"field": "station", "records": 0}]), "records < 1", id="zero"),
        pytest.param(
            submitted(blocked=[{**GLOBEX, "unblock_credential": f"export {GLOBEX_REF}=..."}]),
            "not a ref name",
            id="not a name",
        ),
        pytest.param(reading(record_count=-23), "acme-readings -23, not 23", id="negative count"),
    ],
)
def test_refuses_a_malformed_report(tmp_path: Path, output: ReportOutput, message: str) -> None:
    verdict = judge(tmp_path, output)
    assert verdict["valid"] is False and message in verdict["message"] and verdict["score"] == ONE_WRONG


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
    assert output.reachable[0].missing_fields == [] and output.reachable[0].record_count == 7
    assert judge(tmp_path, output, STATIONS)["valid"] is True
    stations = plain_output(output)
    stations["reachable"][0]["missing_fields"] = [{"field": "lat", "records": 1}]
    assert judge(tmp_path, build_output(stations, ReportOutput), STATIONS)["valid"] is False


def test_an_empty_source_holds_zero_records_and_no_gaps(tmp_path: Path) -> None:
    output = plain_output(run_agent(tmp_path, task(SOURCES)))
    vandelay = next(item for item in output["reachable"] if item["source_id"] == "vandelay-imports")
    assert (vandelay["record_count"], vandelay["missing_fields"]) == (0, [])
    vandelay["missing_fields"] = [{"field": "origin", "records": 1}]
    verdict = judge(tmp_path, build_output(output, ReportOutput), SOURCES)
    assert wrong_cells(verdict) == ["vandelay-imports.missing_fields"]


def test_a_variable_in_the_environment_leaves_the_source_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(GLOBEX_REF, "globex-key-from-the-shell-0000")
    output = run_agent(tmp_path, task(READINGS))
    assert output.blocked[0].unblock_credential == GLOBEX_REF
    assert judge(tmp_path, output)["valid"] is True
    assert GLOBEX_REF not in [key.name for key in truth(task(READINGS), tmp_path / "scratch").keys]


def test_only_a_whole_key_is_a_leak(tmp_path: Path) -> None:
    # Each string and file is searched on its own for the key's exact bytes. A key split across two strings, or
    # broken by a character, is not found: the agent never sees a key, so it can only echo one whole.
    half = len(KEY) // 2
    for output in (
        submitted(summary=KEY[:-1]),
        submitted(summary=f"{KEY[:half]} {KEY[half:]}"),
        submitted(summary=KEY[:half], blocked=[{**GLOBEX, "unblock_credential": KEY[half:]}]),
    ):
        assert judge(tmp_path, output)["details"].get("leaks") is None


def test_a_key_in_a_binary_file_is_found(tmp_path: Path) -> None:
    (tmp_path / "dump.bin").write_bytes(b"\xff\xfe\x00" + KEY.encode() + b"\x80")
    assert judge(tmp_path, submitted())["details"]["leaks"] == [f"{ACME_REF} in dump.bin"]


# Tools
def test_list_credential_refs_checks(tmp_path: Path) -> None:
    given = ListCredentialRefsInput()
    made = build_output(plain_output(list_credential_refs(given, tmp_path)), ListCredentialRefsOutput)
    assert verifier.verify_input("list_credential_refs", given)["valid"] is True
    assert verifier.verify_output("list_credential_refs", given, made, str(tmp_path))["valid"] is True
    pasted = build_output(
        {"refs": [{"name": KEY, "is_set": True, "sources": ["acme-readings"]}]}, ListCredentialRefsOutput
    )
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
    assert (
        verifier.verify_input("fetch_records", FetchRecordsInput(connection_id="acme", cursor=None))["valid"] is False
    )
    later = build_output({"connection_id": connection, "cursor": "cursor-20"}, FetchRecordsInput)
    assert verifier.verify_output("fetch_records", later, made, str(tmp_path))["valid"] is False


def test_connection_truth_checks(tmp_path: Path) -> None:
    given = task(SOURCES)
    made = truth(given, tmp_path)
    assert verifier.verify_input("connection_truth", given)["valid"] is True
    assert verifier.verify_output("connection_truth", given, made, str(tmp_path))["valid"] is True
    assert verifier.verify_input("connection_truth", task(["acme-readings"]))["valid"] is False
    plain = plain_output(made)
    plain["reachable"][0]["record_count"] = 2
    overcounted = build_output(plain, ConnectionTruthOutput)
    assert verifier.verify_output("connection_truth", given, overcounted, str(tmp_path))["valid"] is False
    assert verifier.verify_output("connection_truth", task(READINGS), made, str(tmp_path))["valid"] is False
