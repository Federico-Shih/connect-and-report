"""The connect-and-report task: the submitted report against the pinned connection_truth, and no key leaked.

The verdict is a list of named checks (``details.checks``), each {id, constraint, ok, expected, actual, message}.
The integrity checks come first: any that fails scores 0.0. The outcome checks follow, and score the report by its
cells: a reachable source's record_count and missing_fields, and a blocked source's unblock_credential, each worth
the same. Each entry the report adds beyond one per task source counts as one more wrong cell.
"""

from .checks import CREDENTIAL_REF, digest_problem, duplicates, leaks, result

INTEGRITY = ("reference", "reference-digests", "task-input", "report-submitted", "no-key-leaked")
REACHABLE, BLOCKED = "reachable", "blocked"
# Below 1.0 whatever the measure gives, so only a valid report scores 1.0.
MAX_PARTIAL = 0.99


def missing_problem(missing):
    """Why a missing_fields list is malformed, or None."""
    names = [item.field for item in missing]
    if duplicates(names):
        return f"missing_fields names {', '.join(duplicates(names))} more than once"
    if any(item.records < 1 for item in missing):
        return "missing_fields lists a field no record lacks (records < 1)"
    return None


class Checks:
    """The ordered checks of one verdict. A check whose dependency did not hold is recorded unchecked (ok null)."""

    def __init__(self):
        self.entries = []

    def held(self, check_id):
        return any(entry["id"] == check_id and entry["ok"] for entry in self.entries)

    def add(self, check_id, constraint, needs, judge):
        """``judge()`` -> (ok, expected, actual, message); it runs only when every check in ``needs`` held."""
        blocked = next((need for need in needs if not self.held(need)), None)
        if blocked:
            ok, expected, actual, message = None, None, None, f"Not checked: {blocked} did not hold."
        else:
            ok, expected, actual, message = judge()
            if ok:
                message = ""
        entry = {"id": check_id, "constraint": constraint, "ok": ok, "expected": expected, "actual": actual}
        self.entries.append({**entry, "message": message})
        return ok

    def failed(self):
        return [entry for entry in self.entries if entry["ok"] is False]


def pairs(missing):
    return {(item.field, item.records) for item in missing}


def as_list(items):
    return [{"field": field, "records": records} for field, records in sorted(items)]


def entries(report):
    """Every entry of the report as (side, entry), reachable ones first."""
    return [(REACHABLE, item) for item in report.reachable] + [(BLOCKED, item) for item in report.blocked]


def firsts(report):
    """Each source id -> its first entry, (side, entry): the one judged when a source is listed twice."""
    found = {}
    for side, item in entries(report):
        found.setdefault(item.source_id, (side, item))
    return found


def listed_as(report, source_id, side):
    """The report's first entry for the source, when it is on ``side``; else None."""
    first = firsts(report).get(source_id)
    return first[1] if first and first[0] == side else None


def sentence(items):
    """``items`` joined for a message, the first three named and the rest counted."""
    shown = "; ".join(items[:3])
    return shown + (f"; and {len(items) - 3} more" if len(items) > 3 else "")


def run_checks(arguments, output, reference, workspace):
    """Every check, in order, and what the outcome checks found: (Checks, cells or None, extra, leaks)."""
    checks = Checks()
    found = []
    checks.add(
        "reference",
        "connection_truth pinned the truth before the agent ran.",
        (),
        lambda: (reference is not None, None, None, "No reference: connection_truth was not pinned."),
    )

    def digests():
        problem = digest_problem(reference.keys)
        return problem is None, None, None, f"{problem[:1].upper()}{problem[1:]}." if problem else ""

    checks.add("reference-digests", "Every key digest in the reference is well formed.", ("reference",), digests)

    def task_input():
        expected = sorted(item.source_id for _, item in entries(reference))
        given = sorted(arguments.sources) if arguments is not None else None
        message = f"The task names {given}, but the reference splits {expected}."
        return given == expected, expected, given, message

    checks.add("task-input", "The task names the sources the reference splits.", ("reference",), task_input)
    checks.add(
        "report-submitted",
        "The agent submitted a report.",
        (),
        lambda: (output is not None, None, None, "No report was submitted."),
    )

    def no_leak():
        found.extend(leaks(output, workspace, reference.keys))
        # Names and paths only: the verifier knows a key by its digest and never holds its value.
        message = f"A key value leaked: {'; '.join(found)}."
        return not found, [], found or None, message

    checks.add(
        "no-key-leaked",
        "No key value appears in the report or in any workspace file.",
        ("reference-digests", "report-submitted"),
        no_leak,
    )
    # The outcome checks wait on no-key-leaked: a leaked key may sit in any string they would quote.
    needs = ("reference", "report-submitted", "no-key-leaked")
    task = [item.source_id for _, item in entries(reference)] if reference is not None else []
    cells = {}

    def listed():
        ids = [item.source_id for _, item in entries(output)]
        problems = {
            "omitted": sorted(set(task) - set(ids)),
            "repeated": duplicates([source for source in ids if source in task]),
            "unknown": sorted(set(ids) - set(task)),
        }
        said = [f"{kind} {', '.join(sources)}" for kind, sources in problems.items() if sources]
        message = f"The report's sources differ from the task's: {'; '.join(said)}."
        return not said, sorted(task), {kind: sources for kind, sources in problems.items() if sources}, message

    checks.add(
        "sources-listed",
        "The report lists every task source exactly once, as reachable or blocked, and no other source.",
        needs,
        listed,
    )

    def split():
        truth = firsts(reference)
        given = firsts(output)
        wrong = {
            source: truth[source][0] for source in task if source in given and given[source][0] != truth[source][0]
        }
        said = [
            f"{source} is {side}, not {REACHABLE if side == BLOCKED else BLOCKED}" for source, side in wrong.items()
        ]
        return not wrong, wrong or None, None, f"Sources on the wrong side: {sentence(said)}."

    checks.add("sources-split", "Each task source the report lists is on the side the reference puts it.", needs, split)

    def record_counts():
        wrong, said = {}, []
        for truth in reference.reachable:
            given = listed_as(output, truth.source_id, REACHABLE)
            right = given is not None and given.record_count == truth.record_count
            cells[f"{truth.source_id}.record_count"] = right
            if not right:
                wrong[truth.source_id] = None if given is None else given.record_count
                shown = "not reported reachable" if given is None else f"{given.record_count}, not {truth.record_count}"
                said.append(f"{truth.source_id} {shown}")
        expected = {item.source_id: item.record_count for item in reference.reachable if item.source_id in wrong}
        return not wrong, expected or None, wrong or None, f"Wrong record_count: {sentence(said)}."

    checks.add(
        "record-counts",
        "Each reachable source's record_count is the number of distinct records it holds.",
        needs,
        record_counts,
    )

    def well_formed():
        said = [
            f"{item.source_id}: {missing_problem(item.missing_fields)}"
            for item in output.reachable
            if missing_problem(item.missing_fields)
        ]
        return not said, None, None, f"Malformed missing_fields: {sentence(said)}."

    checks.add(
        "missing-fields-well-formed",
        "Each reachable entry's missing_fields names each field once, each lacked by 1 or more records.",
        needs,
        well_formed,
    )

    def missing_exact():
        expected, actual, said = {}, {}, []
        for truth in reference.reachable:
            given = listed_as(output, truth.source_id, REACHABLE)
            # A malformed list is wrong however close its pairs are.
            right = (
                given is not None
                and missing_problem(given.missing_fields) is None
                and pairs(given.missing_fields) == pairs(truth.missing_fields)
            )
            cells[f"{truth.source_id}.missing_fields"] = right
            if right:
                continue
            if given is None:
                said.append(f"{truth.source_id} not reported reachable")
                continue
            submitted, true = pairs(given.missing_fields), pairs(truth.missing_fields)
            expected[truth.source_id], actual[truth.source_id] = as_list(true - submitted), as_list(submitted - true)
            said.append(f"{truth.source_id} omits {expected[truth.source_id]}, adds {actual[truth.source_id]}")
        ok = all(cells[f"{item.source_id}.missing_fields"] for item in reference.reachable)
        return ok, expected or None, actual or None, f"missing_fields differ: {sentence(said)}."

    checks.add(
        "missing-fields-exact",
        "Each reachable source's missing_fields is exactly the set of (field, records) pairs it has.",
        needs,
        missing_exact,
    )

    def unblock():
        expected, actual, said = {}, {}, []
        for truth in reference.blocked:
            given = listed_as(output, truth.source_id, BLOCKED)
            right = given is not None and given.unblock_credential == truth.unblock_credential
            cells[f"{truth.source_id}.unblock_credential"] = right
            if right:
                continue
            expected[truth.source_id] = truth.unblock_credential
            actual[truth.source_id] = None if given is None else given.unblock_credential
            if given is None:
                said.append(f"{truth.source_id} not reported blocked")
            else:
                named = given.unblock_credential
                kind = "" if CREDENTIAL_REF.fullmatch(named) else "a string that is not a ref name, "
                said.append(f"{truth.source_id} needs {truth.unblock_credential}, not {kind}{named!r}")
        return not said, expected or None, actual or None, f"Wrong unblock_credential: {sentence(said)}."

    checks.add(
        "unblock-credentials",
        "Each blocked source's unblock_credential is the exact ref it accepts.",
        needs,
        unblock,
    )
    if not checks.held("no-key-leaked"):
        return checks, None, 0, found
    extra = len(entries(output)) - len(set(task) & {item.source_id for _, item in entries(output)})
    return checks, cells, extra, found


def verify_task(arguments, output, reference, workspace):
    """``arguments``: the contract ReportInput; ``output``: a contract ReportOutput; ``reference``: the pinned
    ConnectionTruthOutput.

    Any key found verbatim in the output or a workspace file fails no-key-leaked, so the run scores 0.0 however
    right the report is: the verifier knows each key only by its sha256 and length (docs/PLUGINS_PLAN.md §3).
    """
    checks, cells, extra, found = run_checks(arguments, output, reference, workspace)
    details = {"checks": checks.entries}
    if cells is not None:
        details |= {"cells": cells, "extra_entries": extra}
    if found:
        details["leaks"] = found
    failed = checks.failed()
    if not failed:
        records = sum(item.record_count for item in reference.reachable)
        message = (
            f"All {len(checks.entries)} checks hold: the report is exact and leaks no key "
            f"({len(reference.reachable)} reachable sources holding {records} records; "
            f"{len(reference.blocked)} blocked, each with the ref that unblocks it)"
        )
        return result(True, message, score=1.0, **details)
    first = failed[0]
    message = f"{first['id']}: {first['message']}" + (f" (+{len(failed) - 1} more)" if len(failed) > 1 else "")
    integrity = [entry for entry in checks.entries if entry["id"] in INTEGRITY]
    if any(entry["ok"] is not True for entry in integrity) or not cells:
        return result(False, message, score=0.0, **details)
    score = min(round(sum(cells.values()) / (len(cells) + extra), 4), MAX_PARTIAL)
    return result(False, message, score=score, **details)
