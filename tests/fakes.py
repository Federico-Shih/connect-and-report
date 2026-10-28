"""A scripted agent that works the connect-and-report task through the real tools and the server's call path, as an
agent would, so every call lands in the ledger."""

from __future__ import annotations

from pathlib import Path

from slimconfig import build_output, plain_output

from contract import ReportInput, ReportOutput
from plugin.__main__ import run_call
from plugin.fetching import TemporarilyUnavailable


def run_agent(
    workspace: Path,
    task: ReportInput,
    *,
    pages: int | None = None,
    first_ref_only: bool = False,
    count_served: bool = False,
    absent_only: bool = False,
    no_retry: bool = False,
) -> ReportOutput:
    """List the refs, connect to each source with the refs listed for it until one opens it, page through the
    reachable one (retrying a page that fails) and report each record once.

    Each switch makes one mistake: ``pages`` stops after that many pages; ``first_ref_only`` tries only the first
    ref listed for a source and reports it; ``count_served`` counts every record served, repeats included;
    ``absent_only`` counts a field as lacking only when it is absent, not null or ""; ``no_retry`` gives up on a page
    that fails, keeping what it read.
    """
    refs = run_call("list_credential_refs", {}, workspace)["refs"]
    reachable = blocked = blocked_ref = ""
    connection = ""
    for source in task.sources:
        listed = [item for item in refs if source in item["sources"]]
        for item in listed[:1] if first_ref_only else listed:
            try:
                connection = run_call("connect", {"source_id": source, "credential_ref": item["name"]}, workspace)
                reachable = source
                break
            except (ValueError, PermissionError):
                continue
        else:
            blocked = source
            unset = [item["name"] for item in listed if not item["is_set"]]
            blocked_ref = listed[0]["name"] if first_ref_only or not unset else unset[0]
    connection_id = connection["connection_id"] if connection else ""
    records: list[dict] = []
    required: list[str] = []
    cursor: str | None = None
    seen = 0
    while True:
        try:
            fetched = run_call("fetch_records", {"connection_id": connection_id, "cursor": cursor}, workspace)
        except TemporarilyUnavailable:
            if no_retry:
                break
            continue
        required = fetched["required_fields"]
        records.extend(fetched["records"])
        seen += 1
        cursor = fetched["next_cursor"]
        if cursor is None or seen == pages:
            break
    if not count_served:
        records = list({record["id"]: record for record in records}.values())
    lacking: dict[str, int] = {}
    for record in records:
        for field in required:
            absent = field not in record["fields"]
            if absent or (not absent_only and record["fields"][field] in (None, "")):
                lacking[field] = lacking.get(field, 0) + 1
    report = {
        "reachable_source": reachable,
        "record_count": len(records),
        "missing_fields": [{"field": field, "records": count} for field, count in sorted(lacking.items())],
        "blocked_source": blocked,
        "unblock_credential": blocked_ref,
        "summary": f"{reachable} holds {len(records)} records; set {blocked_ref} to unblock {blocked}.",
    }
    # What the sandbox hands the verifier: the output rebuilt from its JSON.
    return build_output(plain_output(build_output(report, ReportOutput)), ReportOutput)
