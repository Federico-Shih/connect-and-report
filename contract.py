"""Each tool's and task's typed input and output (see nanoagent.plugin.v0001.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    LIST_CREDENTIAL_REFS = "list_credential_refs"
    CONNECT = "connect"
    FETCH_RECORDS = "fetch_records"
    CONNECTION_TRUTH = "connection_truth"


class Task(Enum):
    CONNECT_AND_REPORT = "connect-and-report"


SOURCE_ID = "A fixture source's id, e.g. acme-readings"
CREDENTIAL_REF = "A credential reference: the NAME of the credential that holds the key, never its value"
CONNECTION_ID = "The connection id connect returned, e.g. conn-1"
CURSOR = "Where the page starts: null for the first page, else the next_cursor the previous page returned"


@dataclass
class MissingField(Output):
    field: Annotated[str, "A required field some records lack"]
    records: Annotated[int, "How many of the source's records lack it (1 or more)"]


@dataclass
class ReportInput(Output):
    sources: Annotated[list[str], "The source ids to connect to, two or more: each is either reachable or blocked"]


@dataclass
class SourceReport(Output):
    source_id: Annotated[str, "The id of a source a connection was opened to"]
    record_count: Annotated[int, "How many records it holds, over every page, each id once"]
    missing_fields: Annotated[
        list[MissingField],
        "Each of its required fields that at least one of its records lacks, with how many lack it; empty when none do",
    ]


@dataclass
class BlockedSource(Output):
    source_id: Annotated[str, "The id of a source no connection could be opened to"]
    unblock_credential: Annotated[str, "The exact credential ref NAME a person must set to unblock it"]


@dataclass
class ReportOutput(Output):
    reachable: Annotated[list[SourceReport], "Every task source a connection was opened to, each once"]
    blocked: Annotated[list[BlockedSource], "Every task source no connection could be opened to, each once"]
    summary: Annotated[str, "One or two sentences for a person; never a key value"]


@dataclass
class CredentialRef(Output):
    name: Annotated[str, CREDENTIAL_REF]
    is_set: Annotated[bool, "Whether a key is provisioned for it"]
    sources: Annotated[
        list[str], "The ids of the sources this credential is listed for; a listed ref may be revoked or retired there"
    ]


@dataclass
class ListCredentialRefsInput(Output):
    pass


@dataclass
class ListCredentialRefsOutput(Output):
    refs: Annotated[
        list[CredentialRef], "Every credential ref the fixture sources use, by name; values are never shown"
    ]


@dataclass
class ConnectInput(Output):
    source_id: Annotated[str, SOURCE_ID]
    credential_ref: Annotated[str, CREDENTIAL_REF]


@dataclass
class ConnectOutput(Output):
    connection_id: Annotated[str, "The new connection's id, for fetch_records"]
    source_id: Annotated[str, SOURCE_ID]
    credential_ref: Annotated[str, "The credential ref the connection was opened with"]


@dataclass
class Record(Output):
    id: Annotated[str, "The record's id"]
    fields: Annotated[
        dict[str, str | None],
        "The record's fields; a field it lacks is absent, null or the empty string",
    ]


@dataclass
class FetchRecordsInput(Output):
    connection_id: Annotated[str, CONNECTION_ID]
    cursor: Annotated[str | None, CURSOR]


@dataclass
class FetchRecordsOutput(Output):
    source_id: Annotated[str, SOURCE_ID]
    required_fields: Annotated[list[str], "The fields every record of this source must hold"]
    records: Annotated[list[Record], "This page's records, in order"]
    next_cursor: Annotated[str | None, "The cursor of the next page; null when this page is the last"]


@dataclass
class KeyDigest(Output):
    name: Annotated[str, CREDENTIAL_REF]
    sha256: Annotated[str, "The sha256 hex digest of the key's UTF-8 bytes"]
    length: Annotated[int, "The key's length in UTF-8 bytes"]


@dataclass
class ConnectionTruthOutput(Output):
    reachable: Annotated[list[SourceReport], "Each reachable task source's count and missing fields, in task order"]
    blocked: Annotated[list[BlockedSource], "Each blocked task source and the ref it accepts, in task order"]
    keys: Annotated[list[KeyDigest], "Every set key's digest and length, never its value"]


TOOLS = {
    Tool.LIST_CREDENTIAL_REFS: (ListCredentialRefsInput, ListCredentialRefsOutput),
    Tool.CONNECT: (ConnectInput, ConnectOutput),
    Tool.FETCH_RECORDS: (FetchRecordsInput, FetchRecordsOutput),
    Tool.CONNECTION_TRUTH: (ReportInput, ConnectionTruthOutput),
}
TASKS = {Task.CONNECT_AND_REPORT: (ReportInput, ReportOutput)}
