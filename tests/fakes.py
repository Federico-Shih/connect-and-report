"""A scripted agent that works the connect-and-report task through the real tools and the server's call path, as an
agent would, so every call lands in the ledger."""

from __future__ import annotations

from pathlib import Path

from slimconfig import build_output, plain_output

from contract import ReportInput, ReportOutput
from plugin.__main__ import run_call
from plugin.sources import TemporarilyUnavailable


def connect_any(workspace: Path, source: str, listed: list[dict], *, first_ref_only: bool, retry: bool):
    """Try the source's listed refs in turn: (the connection, or None, and the ref connect said is not set)."""
    unset = ""
    for item in listed[:1] if first_ref_only else listed:
        while True:
            try:
                return run_call("connect", {"source_id": source, "credential_ref": item["name"]}, workspace), unset
            except TemporarilyUnavailable:
                if retry:
                    continue
                break
            except (ValueError, PermissionError) as error:
                if "is not set" in str(error):
                    unset = item["name"]
                break
    return None, unset


def read_all(workspace: Path, connection_id: str, *, pages: int | None, retry: bool) -> tuple[list[dict], list[str]]:
    """Every record the source serves, page by page (repeats included), and its required fields."""
    records: list[dict] = []
    required: list[str] = []
    cursor: str | None = None
    seen = 0
    while True:
        try:
            fetched = run_call("fetch_records", {"connection_id": connection_id, "cursor": cursor}, workspace)
        except TemporarilyUnavailable:
            if not retry:
                break
            continue
        required = fetched["required_fields"]
        records.extend(fetched["records"])
        seen += 1
        cursor = fetched["next_cursor"]
        if cursor is None or seen == pages:
            break
    return records, required


def run_agent(
    workspace: Path,
    task: ReportInput,
    *,
    pages: int | None = None,
    first_ref_only: bool = False,
    first_unset: bool = False,
    no_connect_retry: bool = False,
    count_served: bool = False,
    absent_only: bool = False,
    count_optional: bool = False,
    no_retry: bool = False,
    every_listed: bool = False,
) -> ReportOutput:
    """List the refs, connect to each source with the refs listed for it until one opens it (retrying a connect
    that fails), page through every reachable one (retrying a page that fails) and report each record once; name,
    for each blocked source, the ref connect said is not set.

    Each switch makes one mistake: ``pages`` stops each source after that many pages; ``first_ref_only`` tries only
    the first ref listed for a source and reports it; ``first_unset`` names a blocked source's first unset listed
    ref; ``no_connect_retry`` gives up on a connect that fails once; ``count_served`` counts every record served,
    repeats included; ``absent_only`` counts a field as lacking only when it is absent, not null or "";
    ``count_optional`` counts every field records lack, required or not; ``no_retry`` gives up on a page that fails,
    keeping what it read; ``every_listed`` also reports the sources the refs list that the task does not name.
    """
    refs = run_call("list_credential_refs", {}, workspace)["refs"]
    sources = list(task.sources)
    if every_listed:
        sources += [source for item in refs for source in item["sources"] if source not in sources]
        sources = list(dict.fromkeys(sources))
    reachable: list[dict] = []
    blocked: list[dict] = []
    for source in sources:
        listed = [item for item in refs if source in item["sources"]]
        connection, unset = connect_any(
            workspace, source, listed, first_ref_only=first_ref_only, retry=not no_connect_retry
        )
        if connection is None:
            named = [item["name"] for item in listed if not item["is_set"]][:1] if first_unset else [unset]
            if first_ref_only or not named[0]:
                named = [listed[0]["name"]]
            blocked.append({"source_id": source, "unblock_credential": named[0]})
            continue
        records, required = read_all(workspace, connection["connection_id"], pages=pages, retry=not no_retry)
        if not count_served:
            records = list({record["id"]: record for record in records}.values())
        fields = sorted({field for record in records for field in record["fields"]}) if count_optional else required
        lacking: dict[str, int] = {}
        for record in records:
            for field in fields:
                absent = field not in record["fields"]
                if absent or (not absent_only and record["fields"][field] in (None, "")):
                    lacking[field] = lacking.get(field, 0) + 1
        missing = [{"field": field, "records": count} for field, count in sorted(lacking.items())]
        reachable.append({"source_id": source, "record_count": len(records), "missing_fields": missing})
    report = {
        "reachable": reachable,
        "blocked": blocked,
        "summary": f"{len(reachable)} sources reachable; {len(blocked)} blocked, each with the ref to set.",
    }
    # What the sandbox hands the verifier: the output rebuilt from its JSON.
    return build_output(plain_output(build_output(report, ReportOutput)), ReportOutput)
