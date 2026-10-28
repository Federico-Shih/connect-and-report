# Connect and Report

A `nanoagent.plugin/v0001` plugin, created by `nanoagent plugin new` with the
structure of NanoAgent's reference plugin,
[arxiv-source](https://github.com/zeyuyang8/arxiv-source).

An agent connects to the fixture sources a task names, with credential
references (the names of the credentials that hold their keys), never raw keys.
For each reachable source it counts every record and reports which required
fields some records lack; for each blocked one it names the exact credential a
person must set. The sources ship in `src/plugin/fixtures/sources.json` and
their mock APIs run in the plugin process, so every run is the same and needs
no network. `tests/make_fixtures.py` regenerates the sources after
`globex-claims` from a fixed seed.

There is nothing to set before running. The keys are fixtures too:
`src/plugin/fixtures/credentials.json` holds a key for some refs and none for
the refs a blocked source accepts, which are the credentials the report must
name. The plugin never reads its environment for a key, so a variable of any
ref's name changes nothing.

The default example names nine sources, five reachable and four blocked, and
each sets a trap that makes a plausible answer wrong:

- **Distractor refs.** `list_credential_refs` lists 15 refs, some for sources
  the task does not name (`umbrella-archive`, `initech-archive`,
  `acme-stations`). Only the task's sources belong in the report.
- **Revoked refs.** A set ref a source lists but rejects: `connect` says the key
  was revoked. `globex-claims` lists `CONNECT_REPORT_GLOBEX_KEY_LEGACY` first,
  `initech-tickets` lists `CONNECT_REPORT_INITECH_KEY_V1` first, and
  `umbrella-trials` lists `CONNECT_REPORT_UMBRELLA_TOKEN` first.
- **Retired refs.** An unset ref a source lists but no longer accepts: setting it
  would not unblock the source, and `connect` says so. `umbrella-trials` lists
  `CONNECT_REPORT_UMBRELLA_READONLY_KEY`, `wayne-ledger` lists
  `CONNECT_REPORT_WAYNE_ARCHIVE_KEY`, and `stark-assets` lists
  `CONNECT_REPORT_STARK_API_KEY`. The ref to report is the one whose `connect`
  error says it is not set.
- **A shared ref.** `CONNECT_REPORT_SHARED_PARTNER_KEY` opens `stark-assets` but
  is revoked for `wayne-ledger`.
- **A flaky connect.** `hooli-events` refuses the first `connect` with
  `temporarily unavailable (HTTP 503)`. It is reachable.
- **Flaky pages.** Page 2 of `acme-readings`, and two pages of
  `initech-tickets`, fail once and serve when asked again.
- **Repeats.** `acme-readings` serves `r-010` twice, at a page boundary.
  `initech-tickets` serves 62 records, 4 of them repeats, some pages apart.
  `hooli-events` serves one record twice. Each record counts once, by id.
- **Empty values.** A record lacks a required field it does not hold, or holds
  as `null` or `""`.
- **Optional fields.** Each source's `required_fields` differs, and records hold
  optional fields that are often empty. They never count as missing.
- **An empty source.** `vandelay-imports` is reachable and holds 0 records.

The answer for the default example, `tests/examples/connect-and-report.json`:

| Source | Answer |
|---|---|
| `acme-readings` | 23 records; `humidity_pct` missing in 2, `recorded_at` in 1, `temperature_c` in 4 |
| `initech-tickets` | 58 records; `assignee` in 7, `opened_at` in 2, `priority` in 3, `queue` in 5 |
| `hooli-events` | 37 records; `capacity` in 6, `organizer` in 1, `venue` in 4 |
| `stark-assets` | 26 records; `model` in 2, `purchased_on` in 3 |
| `vandelay-imports` | 0 records, none missing |
| `globex-claims` | blocked: `CONNECT_REPORT_GLOBEX_API_KEY` |
| `umbrella-trials` | blocked: `CONNECT_REPORT_UMBRELLA_API_KEY` |
| `wayne-ledger` | blocked: `CONNECT_REPORT_WAYNE_LEDGER_KEY` |
| `soylent-orders` | blocked: `CONNECT_REPORT_SOYLENT_API_KEY` |

`tests/examples/connect-and-report-easy.json` names only `acme-readings` and
`globex-claims`, the task's first, two-source form.

## Tools

| Tool | Does | Code |
|---|---|---|
| `list_credential_refs` | Lists every credential ref by name, whether it is set, and which sources it is listed for; never a value | `src/plugin/credentials.py` |
| `connect` | Opens a connection to a source with a credential ref, resolved from the bundled credential store; an unknown, unset, revoked, retired or wrong ref raises, naming refs only; a flaky source fails its first connect | `src/plugin/connecting.py` |
| `fetch_records` | Returns one page (10 records) of a connected source's records, as served (a record may repeat across pages), and its required fields; a flaky page fails once | `src/plugin/fetching.py` |
| `connection_truth` | The hidden reference: each task source as reachable (its unique record count and missing fields) or blocked (the ref it accepts), and the sha256 and length of every set key, revoked ones included | `src/plugin/truth.py` |

### Tasks

| Task | Does | Runner |
|---|---|---|
| `connect-and-report` | Connects to each of the task's sources (2 or more) and reports `reachable` (each source's `source_id`, `record_count` and `missing_fields`), `blocked` (each source's `source_id` and `unblock_credential`) and a `summary`; checked against `connection_truth` | `agent`, with `list_credential_refs`, `connect` and `fetch_records` |

`missing_fields` is per reachable source and per field: each required field that at least one record
lacks (absent from its `fields`, `null` or `""`), with how many records lack it,
each record counted once; it is empty when none do.

## Checks

`verify_task` in `verifier/report.py` judges the submitted report against 11
checks, in order. Every entry of the verdict's `details.checks` has the same
keys: `{id, constraint, ok, expected, actual, message}`. `ok` is `true`
(holds), `false` (fails) or `null` (not checked, because a check it needs did
not hold). `expected` and `actual` are set where they say something concrete
(for `missing-fields-exact`, the omitted and the extra pairs per source) and are
`null` otherwise. `message` is `""` when the check holds, the reason when it
fails, and `"Not checked: <id> did not hold."` when it was skipped. No entry
ever holds a key value: the outcome checks (6 to 11) wait on `no-key-leaked`,
because a leaked key may sit in any string they would quote. A message lists
at most three items and counts the rest.

| # | id | What it checks | Example failure message |
|---|---|---|---|
| 1 | `reference` | `connection_truth` pinned the truth before the agent ran | No reference: connection_truth was not pinned. |
| 2 | `reference-digests` | Every key digest in the reference is well formed | The reference's digest of 'CONNECT_REPORT_ACME_API_KEY' is malformed. |
| 3 | `task-input` | The task names the sources the reference splits | The task names ['acme-readings', 'globex-claims'], but the reference splits ['acme-stations', 'globex-claims']. |
| 4 | `report-submitted` | The agent submitted a report | No report was submitted. |
| 5 | `no-key-leaked` | No key value appears in the report or in any workspace file | A key value leaked: CONNECT_REPORT_ACME_API_KEY in the output. |
| 6 | `sources-listed` | The report lists every task source exactly once, as reachable or blocked, and no other source | The report's sources differ from the task's: omitted vandelay-imports; unknown umbrella-archive. |
| 7 | `sources-split` | Each task source the report lists is on the side the reference puts it | Sources on the wrong side: hooli-events is reachable, not blocked. |
| 8 | `record-counts` | Each reachable source's `record_count` is the number of distinct records it holds | Wrong record_count: initech-tickets 62, not 58. |
| 9 | `missing-fields-well-formed` | Each `missing_fields` names each field once, each lacked by 1 or more records | Malformed missing_fields: acme-readings: missing_fields names humidity_pct more than once. |
| 10 | `missing-fields-exact` | Each reachable source's `missing_fields` is exactly the set of (field, records) pairs it has | missing_fields differ: initech-tickets omits [{'field': 'queue', 'records': 5}], adds []. |
| 11 | `unblock-credentials` | Each blocked source's `unblock_credential` is the exact ref it accepts | Wrong unblock_credential: umbrella-trials needs CONNECT_REPORT_UMBRELLA_API_KEY, not 'CONNECT_REPORT_UMBRELLA_READONLY_KEY'. |

A source the report lists twice is judged by its first entry, reachable ones
first. `no-key-leaked` hashes every run of key-length bytes in each string of
the report and in each workspace file (the ledger included) and compares it
with the reference's digest, so the verifier never holds a key. A key split
across strings or broken by a character is not a leak.

### How it is scored

- **Valid** only when all 11 checks hold; the score is then 1.0.
- **Score 0** when any of checks 1 to 5 fails or is not checked: they guard the
  reference and the report's integrity. A leaked key scores 0 however right the
  report is.
- **Otherwise** the score is the share of right cells, at most 0.99. Each
  reachable source has two cells, `<id>.record_count` and `<id>.missing_fields`
  (a malformed list is wrong), and each blocked source has one,
  `<id>.unblock_credential`: the default example has 14 cells, the easy one 3.
  A source on the wrong side or left out loses all its cells, and each entry for
  a source the task does not name adds one wrong cell to the total. Every cell
  weighs the same: each is a finding a person would act on separately, and each
  trap costs only the cells it touches (a retired ref named costs that source's
  `unblock_credential`, a skipped page costs its source's two cells), so the
  score says how much of the report a person could trust.
- **The message** names the first failing check, why it fails, and how many more
  fail, e.g. `record-counts: Wrong record_count: acme-readings 10, not 23. (+1
  more)`. A valid verdict says `All 11 checks hold: the report is exact and
  leaks no key (5 reachable sources holding 144 records; 4 blocked, each with
  the ref that unblocks it)`.
- **`details`** also holds `cells` (each cell and whether it is right),
  `extra_entries` and, when a key leaked, `leaks`: where each one appeared, by
  ref name and file path only.

## Layout

```text
.
├── nanoagent.yaml   # manifest (a slimconfig ManifestConfig): id, runtime, permissions, tools, tasks
├── contract.py      # each tool's and task's typed input and output: slimconfig Output classes
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env             # environment variable NAMEs this plugin needs, never values (none)
├── src/plugin/      # the MCP server: __main__.py, its IMPLEMENTATIONS, one module per tool, engine.py
│   └── fixtures/    # the mock sources and their records, sources.json, and their keys, credentials.json
├── tests/
│   ├── run_agent.sh # one agent run on OpenRouter: config, nanoagent plugin agent, verdict
│   ├── examples/    # the task's example arguments, <id>.json
│   └── results/     # one folder per agent run (git-ignored)
├── ui/              # how the page draws the outputs: renderers.js and renderers.css
├── product/         # the product page a catalog shows: product.yaml and icon.svg
└── verifier/        # deterministic verifier package
```

`contract.py` is the one place a value's shape is declared. Its `Output`
classes are the JSON Schemas the server offers and the agent sees, and every
input and output is built into its class on the way in and out: the server,
NanoAgent and the verifier all get typed values, never loose dicts. A tool
that fails raises; NanoAgent sees an MCP error.

To add a tool: add a `Tool` member, its input and output classes and its
`TOOLS` entry to `contract.py` (a snake_case name, classes named `...Input`
and `...Output`); write its implementation in `src/plugin/`, taking its input
and the workspace and returning its output; write its `verify_input` /
`verify_output` in `verifier/`, and tests for both. Then register it in
`src/plugin/__main__.py` (`IMPLEMENTATIONS`), `verifier/__init__.py` (`TOOLS`),
`nanoagent.yaml` (`tools`) and this README's Tools table; a task goes in its
Tasks table.

`LICENSE` stays the template's MIT license under your name, `.gitignore`
keeps its entries, and this README keeps its title and sections: NanoAgent refuses a plugin
that changes them (rule 10 of `nanoagent.plugin.manifest`). Renaming the
plugin means renaming it in `nanoagent.yaml` and this title together.

To add a task, add a `Task` member (a kebab-case id) and its `TASKS` input and
output classes to `contract.py`, and declare it in `nanoagent.yaml` with its `runner` (`tool`,
`agent` or `decide`) and a `reference` tool, or `null` if it has none. A `tool`
task's classes are its tool's; an `agent` task's agent ends by calling `submit`
with the task's output; a `decide` task's model only chooses, and every tool
argument and output field is an Enum or bool, or copied from a value of exactly
its type in the task's input or an earlier tool output. Then add the check of
its output, `verify_task(arguments, output, reference, workspace)`, to `TASKS`
in `verifier/__init__.py`. People use the plugin by chatting with its agent,
which runs its tasks and shows each output on the page (see `ui/`).

## Develop and run

```bash
uv sync --extra dev
uv run pytest && uv run ruff check . && uv lock --check
```

Run the task with `nanoagent plugin agent`: its run config names this plugin, the `connect-and-report` task and its `sources`
argument: the nine sources of `tests/examples/connect-and-report.json`, the two
of `tests/examples/connect-and-report-easy.json`, or any 2 or more sources of
`sources.json` (`[acme-stations, globex-claims]`'s records lack no required
field).

To run the agent, with NanoAgent on `PATH` and an OpenRouter key:

```bash
export OPENROUTER_API_KEY=...          # or ENV_FILE=path/to/keys.env
tests/run_agent.sh                     # tests/examples/connect-and-report.json
tests/run_agent.sh tests/examples/connect-and-report-easy.json
tests/run_agent.sh path/to/arguments.json
```

The script writes a NanoAgent run config (`PluginOpenRouterAgentConfig`), runs
`nanoagent plugin agent`, prints the verdict and exits 0 only when it is
valid. Each run goes to `tests/results/<time>/`, next to the config it ran as
`tests/results/<time>.yaml`: `result.json` (what the agent submitted),
`verdict.json`, `reference.json` (the pinned reference), `messages.json` (the
trajectory), `run.log` and `workspace/` with `.ledger/calls.jsonl`. `MODEL`,
`MAX_STEPS` and `TIMEOUT` override the defaults (`deepseek/deepseek-v4-flash`,
120 steps, 60 seconds per tool call). The default example takes about 40 tool
calls when nothing goes astray, so leave room for retries and wrong turns.

Publishing checks every plugin rule: push the plugin to a public GitHub
repository and run `rush publish <server> <github-url>`.
