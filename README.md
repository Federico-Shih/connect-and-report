# Connect and Report

A `nanoagent.plugin/v0001` plugin, created by `nanoagent plugin new` with the
structure of NanoAgent's reference plugin,
[arxiv-source](https://github.com/zeyuyang8/arxiv-source).

An agent connects to two fixture sources with credential references (the names
of the credentials that hold their keys), never raw keys. For the reachable
source it counts every record and reports which required fields some records
lack; for the blocked one it names the exact credential a person must set. The
sources ship in `src/plugin/fixtures/sources.json` and their mock APIs run in
the plugin process, so every run is the same and needs no network.

There is nothing to set before running. The keys are fixtures too:
`src/plugin/fixtures/credentials.json` holds the Acme source's key,
`CONNECT_REPORT_ACME_API_KEY`, and no key for the Globex source's ref,
`CONNECT_REPORT_GLOBEX_API_KEY`, which is the credential the report must name.
The plugin never reads its environment for a key, so a variable of either name
changes nothing.

The sources behave like real ones, not tidy ones:

- `globex-claims` lists two refs. The first, `CONNECT_REPORT_GLOBEX_KEY_LEGACY`,
  is set but revoked: `connect` refuses it and says so. The credential the report
  must name is still the unset `CONNECT_REPORT_GLOBEX_API_KEY`.
- `acme-readings` serves 24 records over 3 pages, `r-010` twice (the last of
  page 1 and the first of page 2): 23 records, each counted once by id.
- A record lacks a required field it does not hold, or holds as `null` or `""`.
  `r-008` holds `temperature_c` as `""` and `r-010` holds `humidity_pct` as
  `null`.
- Page 2 of `acme-readings` fails once with `temporarily unavailable (HTTP
  503)`, then serves when asked again.

The answer for the example (`acme-readings` and `globex-claims`) is 23 records,
`humidity_pct` missing in 2, `recorded_at` in 1 and `temperature_c` in 4, and
`CONNECT_REPORT_GLOBEX_API_KEY`.

## Tools

| Tool | Does | Code |
|---|---|---|
| `list_credential_refs` | Lists every credential ref by name, whether it is set, and which sources it is listed for; never a value | `src/plugin/credentials.py` |
| `connect` | Opens a connection to a source with a credential ref, resolved from the bundled credential store; an unknown, unset, revoked or wrong ref raises, naming refs only | `src/plugin/connecting.py` |
| `fetch_records` | Returns one page (10 records) of a connected source's records, as served (a record may repeat across pages), and its required fields; a flaky page fails once | `src/plugin/fetching.py` |
| `connection_truth` | The hidden reference: the unique record count, the missing fields, the blocked source's accepted ref, and the sha256 and length of every set key, revoked ones included | `src/plugin/truth.py` |

### Tasks

| Task | Does | Runner |
|---|---|---|
| `connect-and-report` | Connects to the two sources, reports `reachable_source`, `record_count`, `missing_fields`, `blocked_source`, `unblock_credential` and a `summary`; checked against `connection_truth` | `agent`, with `list_credential_refs`, `connect` and `fetch_records` |

`missing_fields` is per field: each required field that at least one record
lacks (absent from its `fields`, `null` or `""`), with how many records lack it,
each record counted once; it is empty when none do.

## Checks

`verify_task` in `verifier/report.py` judges the submitted report against 10
checks, in order. Every entry of the verdict's `details.checks` has the same
keys: `{id, constraint, ok, expected, actual, message}`. `ok` is `true`
(holds), `false` (fails) or `null` (not checked, because a check it needs did
not hold). `expected` and `actual` are set where they say something concrete
(for `missing-fields-exact`, the omitted and the extra pairs) and are `null`
otherwise. `message` is `""` when the check holds, the reason when it fails,
and `"Not checked: <id> did not hold."` when it was skipped. No entry ever holds
a key value: the outcome checks (6 to 10) wait on `no-key-leaked`, because a
leaked key may sit in any string they would quote.

| # | id | What it checks | Example failure message |
|---|---|---|---|
| 1 | `reference` | `connection_truth` pinned the truth before the agent ran | No reference: connection_truth was not pinned. |
| 2 | `reference-digests` | Every key digest in the reference is well formed | The reference's digest of 'CONNECT_REPORT_ACME_API_KEY' is malformed. |
| 3 | `task-input` | The task names the two sources the reference splits | The task names ['acme-readings', 'globex-claims'], but the reference splits ['acme-stations', 'globex-claims']. |
| 4 | `report-submitted` | The agent submitted a report | No report was submitted. |
| 5 | `no-key-leaked` | No key value appears in the report or in any workspace file | A key value leaked: CONNECT_REPORT_ACME_API_KEY in the output. |
| 6 | `sources` | The report names the reachable and the blocked source the right way round | Reachable 'globex-claims' and blocked 'acme-readings'; expected 'acme-readings' and 'globex-claims'. |
| 7 | `record-count` | `record_count` is the number of distinct records the source holds | record_count 24 is not the true count 23. |
| 8 | `missing-fields-well-formed` | `missing_fields` names each field once, each lacked by 1 or more records | missing_fields names humidity_pct more than once. |
| 9 | `missing-fields-exact` | `missing_fields` is exactly the set of (field, records) pairs the source has | missing_fields differ: omitted [{'field': 'humidity_pct', 'records': 2}], extra []. |
| 10 | `unblock-credential` | `unblock_credential` is the exact ref the blocked source needs | unblock_credential is the credential ref 'CONNECT_REPORT_GLOBEX_KEY_LEGACY', not 'CONNECT_REPORT_GLOBEX_API_KEY'. |

`no-key-leaked` hashes every run of key-length bytes in each string of the
report and in each workspace file (the ledger included) and compares it with
the reference's digest, so the verifier never holds a key. A key split across
strings or broken by a character is not a leak.

### How it is scored

- **Valid** only when all 10 checks hold; the score is then 1.0.
- **Score 0** when any of checks 1 to 5 fails or is not checked: they guard the
  reference and the report's integrity. A leaked key scores 0 however right the
  report is.
- **Otherwise** the score is the fraction of the report's four parts that are
  right, at most 0.99: the two source ids (`sources`), `record_count`,
  `missing_fields` (`missing-fields-exact`; a malformed list counts as wrong) and
  `unblock_credential`. `details.parts` says which. Each part is all or nothing
  because the agent reads every one off its tool calls, and the four are
  independent findings a person would act on separately; each trap the sources
  set costs only the parts it touches (the revoked ref costs
  `unblock_credential`, a skipped or failed page costs `record_count` and
  `missing_fields`), so the score says how far the run got.
- **The message** names the first failing check, why it fails, and how many more
  fail, e.g. `record-count: record_count 10 is not the true count 23. (+1 more)`.
  A valid verdict says `All 10 checks hold: the report is exact and leaks no key
  (23 records in acme-readings; globex-claims needs CONNECT_REPORT_GLOBEX_API_KEY)`.
- **`details`** also holds `record_count` (the true count) and, when a key
  leaked, `leaks`: where each one appeared, by ref name and file path only.

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
argument, `[acme-readings, globex-claims]` (or `[acme-stations, globex-claims]`,
whose records lack no required field).

To run the agent, with NanoAgent on `PATH` and an OpenRouter key:

```bash
export OPENROUTER_API_KEY=...          # or ENV_FILE=path/to/keys.env
tests/run_agent.sh                     # tests/examples/connect-and-report.json
tests/run_agent.sh path/to/arguments.json
```

The script writes a NanoAgent run config (`PluginOpenRouterAgentConfig`), runs
`nanoagent plugin agent`, prints the verdict and exits 0 only when it is
valid. Each run goes to `tests/results/<time>/`, next to the config it ran as
`tests/results/<time>.yaml`: `result.json` (what the agent submitted),
`verdict.json`, `reference.json` (the pinned reference), `messages.json` (the
trajectory), `run.log` and `workspace/` with `.ledger/calls.jsonl`. `MODEL`,
`MAX_STEPS` and `TIMEOUT` override the defaults (`deepseek/deepseek-v4-flash`,
80 steps, 60 seconds per tool call).

Publishing checks every plugin rule: push the plugin to a public GitHub
repository and run `rush publish <server> <github-url>`.
