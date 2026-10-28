from __future__ import annotations

import json
from pathlib import Path

from plugin.sources import keys

ACME_REF = "CONNECT_REPORT_ACME_API_KEY"
GLOBEX_REF = "CONNECT_REPORT_GLOBEX_API_KEY"
# Listed for globex-claims before GLOBEX_REF, and set, but revoked: globex-claims rejects it.
LEGACY_REF = "CONNECT_REPORT_GLOBEX_KEY_LEGACY"
# Listed for umbrella-trials before the ref it accepts: a set one it revoked, and an unset one it retired.
UMBRELLA_REF = "CONNECT_REPORT_UMBRELLA_API_KEY"
UMBRELLA_REVOKED = "CONNECT_REPORT_UMBRELLA_TOKEN"
UMBRELLA_RETIRED = "CONNECT_REPORT_UMBRELLA_READONLY_KEY"
# stark-assets accepts it; wayne-ledger lists it first, revoked.
PARTNER_REF = "CONNECT_REPORT_SHARED_PARTNER_KEY"
# The keys as the bundled credential store holds them: what a leak hunt must never find.
KEY = keys()[ACME_REF]
LEGACY_KEY = keys()[LEGACY_REF]
PARTNER_KEY = keys()[PARTNER_REF]

EXAMPLES = Path(__file__).with_name("examples")
# The hard example: nine sources, five reachable and four blocked.
SOURCES = json.loads((EXAMPLES / "connect-and-report.json").read_text())["sources"]
# The easy example: acme-readings, reachable, and globex-claims, blocked.
READINGS = json.loads((EXAMPLES / "connect-and-report-easy.json").read_text())["sources"]
