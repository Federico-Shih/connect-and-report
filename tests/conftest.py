from __future__ import annotations

from plugin.sources import keys

ACME_REF = "CONNECT_REPORT_ACME_API_KEY"
GLOBEX_REF = "CONNECT_REPORT_GLOBEX_API_KEY"
# Listed for globex-claims before GLOBEX_REF, and set, but revoked: globex-claims rejects it.
LEGACY_REF = "CONNECT_REPORT_GLOBEX_KEY_LEGACY"
# The keys as the bundled credential store holds them: what a leak hunt must never find.
KEY = keys()[ACME_REF]
LEGACY_KEY = keys()[LEGACY_REF]
