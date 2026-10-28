"""connection_truth, the reference tool: every task source once, consistent counts, digests that can be searched."""

from .checks import CREDENTIAL_REF, digest_problem, result
from .report import missing_problem


def verify_input(value):
    if len(value.sources) < 2 or len(set(value.sources)) != len(value.sources):
        return result(False, "sources must name two or more different sources, each once")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    ids = [item.source_id for item in output_value.reachable] + [item.source_id for item in output_value.blocked]
    if sorted(ids) != sorted(input_value.sources):
        return result(False, "the truth does not split the requested sources into reachable and blocked, each once")
    for item in output_value.reachable:
        problem = missing_problem(item.missing_fields)
        if problem:
            return result(False, f"{item.source_id}: {problem}")
        if item.record_count < 0 or any(gap.records > item.record_count for gap in item.missing_fields):
            return result(False, f"{item.source_id}: a field is missing from more records than the source holds")
    if any(not CREDENTIAL_REF.fullmatch(item.unblock_credential) for item in output_value.blocked):
        return result(False, "an unblock_credential is not a credential ref name")
    problem = digest_problem(output_value.keys)
    if problem:
        return result(False, problem)
    return result(True, f"{len(output_value.reachable)} reachable and {len(output_value.blocked)} blocked sources")
