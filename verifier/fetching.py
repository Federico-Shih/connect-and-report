"""fetch_records: a page of at most PAGE_SIZE records, none repeated, and a cursor that follows a full page."""

from .checks import CONNECTION_ID, CURSOR, PAGE_SIZE, duplicates, result


def verify_input(value):
    if not CONNECTION_ID.fullmatch(value.connection_id):
        return result(False, f"{value.connection_id!r} is not a connection id connect returns")
    if value.cursor is not None and not CURSOR.fullmatch(value.cursor):
        return result(False, f"cursor {value.cursor!r} is not one a page returned")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    records = output_value.records
    if len(records) > PAGE_SIZE:
        return result(False, f"a page holds at most {PAGE_SIZE} records, not {len(records)}")
    ids = [record.id for record in records]
    if duplicates(ids):
        return result(False, "the page repeats a record", ids=ids)
    if duplicates(list(output_value.required_fields)):
        return result(False, "a required field is named twice")
    following = output_value.next_cursor
    if following is not None:
        given = CURSOR.fullmatch(input_value.cursor or "cursor-0")
        found = CURSOR.fullmatch(following)
        start = int(given.group(1)) if given else -1
        if not found or int(found.group(1)) != start + PAGE_SIZE or len(records) != PAGE_SIZE:
            return result(False, f"next_cursor {following!r} does not follow a full page")
    return result(True, f"a page of {len(records)} records", last=following is None)
