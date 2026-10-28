"""connect: opened with a credential ref NAME, never a key value."""

from .checks import CONNECTION_ID, CREDENTIAL_REF, SOURCE_ID, result


def verify_input(value):
    if not SOURCE_ID.fullmatch(value.source_id):
        return result(False, f"{value.source_id!r} is not a source id")
    if not CREDENTIAL_REF.fullmatch(value.credential_ref):
        return result(
            False, "credential_ref must be a ref NAME (upper case, like list_credential_refs lists), never a key value"
        )
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if not CONNECTION_ID.fullmatch(output_value.connection_id):
        return result(False, f"{output_value.connection_id!r} is not a connection id")
    if (output_value.source_id, output_value.credential_ref) != (input_value.source_id, input_value.credential_ref):
        return result(False, "the connection is not to the requested source with the requested ref")
    return result(True, f"connected to {output_value.source_id}", connection_id=output_value.connection_id)
