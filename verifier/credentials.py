"""list_credential_refs: ref names only, each once, each opening known-looking sources."""

from .checks import CREDENTIAL_REF, SOURCE_ID, duplicates, result


def verify_input(value):
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    names = [ref.name for ref in output_value.refs]
    if duplicates(names) or not all(CREDENTIAL_REF.fullmatch(name) for name in names):
        return result(False, "the refs are not unique ref names", names=names)
    if not all(SOURCE_ID.fullmatch(source) for ref in output_value.refs for source in ref.sources):
        return result(False, "a ref names a source id of the wrong form")
    return result(True, f"{len(names)} credential refs", set=[ref.name for ref in output_value.refs if ref.is_set])
