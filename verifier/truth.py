"""connection_truth, the reference tool: two different sources, consistent counts, digests that can be searched."""

from .checks import CREDENTIAL_REF, digest_problem, result
from .report import missing_problem


def verify_input(value):
    if len(value.sources) != 2 or len(set(value.sources)) != 2:
        return result(False, "sources must name two different sources")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if {output_value.reachable_source, output_value.blocked_source} != set(input_value.sources):
        return result(False, "the truth does not split the requested sources into one reachable and one blocked")
    problem = missing_problem(output_value.missing_fields) or digest_problem(output_value.keys)
    if problem:
        return result(False, problem)
    if output_value.record_count < 0 or any(item.records > output_value.record_count for item in output_value.missing_fields):
        return result(False, "a field is missing from more records than the source holds")
    if not CREDENTIAL_REF.fullmatch(output_value.unblock_credential):
        return result(False, "unblock_credential is not a credential ref name")
    return result(True, f"{output_value.record_count} records; {output_value.blocked_source} needs a ref")
