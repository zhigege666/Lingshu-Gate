# 0.4.1 validation record

[简体中文](zh-CN/release-validation-0.4.1.md) · [0.4.0 historical record](release-validation.md)

This patch adds bounded authorization language hints, runtime version display,
built-in OAuth setup prerequisites and personal grant review. Source version,
release-note heading and both README overviews are 0.4.1. The 0.4.0 screenshot
gallery and validation record remain historical evidence.

## Executed source and automated checks

- `uv run ruff check .`: passed.
- `uv run mypy`: passed, 106 source files.
- `uv run pytest -q`: 1,067 passed on local Python 3.12.14. An initial run found
  that this worktree materialized two tracked executable launchers as `0700`.
  Restoring their tracked `100755` mode produced no source-mode diff; the full
  rerun passed.
- `npm --prefix web run check`: type and UI source checks passed.
- `npm --prefix web test`: 66 files, 391 tests passed.
- `npm --prefix web run build`: Console and independent OAuth bundles passed;
  existing large-chunk warnings remain.
- Repository identity, Compose configuration and `git diff --check`: passed.
- `npm --prefix web run e2e:full`: 196 passed, 38 opt-in skips, in 6.8 minutes.
  No retries. Final evidence includes 52 login and 100 OAuth screenshots, plus
  two separately identified optional visual failure images.

ASGI security tests use synthetic credentials and temporary databases. They
cover the original eight authorization fields and additional `ui_locales`,
language preference/fallback, absence from the security ticket, the complete
authorize/login/consent/token path, required resource, exact callback, PKCE,
unknown/duplicate parameters and unchanged query/value/field limits. Saving
disabled URLs without a key succeeds; enabling without one remains rejected
by the existing backend guard.

Browser tests use actual compiled assets. OAuth management and consent APIs are
controlled synthetic responses: no live signing-key/client generation or real
ChatGPT connection is performed. Coverage includes language hints without
changing tickets or stored preferences, manual URL preservation, no autosave,
key-loading/read failures and retries, fresh-state reads after mock key
operations, explicit enable/disable confirmations, dismissible/expiring secret-
free messages, and preservation of one-time-secret close protection.

Personal grant coverage includes 0/1/1,000 records, complete-dataset filtering
before pagination, status/search reset, UTC timestamps without invented creation
dates, 100 MCPs/5,000 tools, searchable read-only historical details, keyboard
close/focus return and explicit reduction/revocation confirmations. Mutations
still use existing owner-scoped APIs and revision checks. Rapid confirmation
reopening keeps its content above the overlay.

Both languages and themes are captured at 1600×900, 1920×1080, 2560×1080 and
2560×1440. Login screenshots use the actual synthetic loopback instance's health
metadata; failure cases explicitly mock that metadata. OAuth screenshots always
mock their APIs. Screenshots establish rendered behavior, not external OAuth
acceptance. Independent review applies to the final source head and evidence.

## Recovery review correction

Independent review reproduced a clipped grant-details pager in both languages
and themes at 1600×900, 1920×1080 and 2560×1080. The outer dialog needed about
185 px of extra scrolling; 2560×1440 already fit. Read-only grant details now
constrain the table's internal viewport with local flex/min-height rules. The
existing search, 50-row pagination, recorded history and Close action remain.
No consent/reduction layout, authorization API or confirmation was changed.

After the correction, all 16 desktop/language/theme combinations place the
pager inside the initial dialog body, with zero outer overflow and successful
hit testing. Separate geometry captures use 5,000 tools across 100 MCPs. The
26-case personal-grant browser suite passes without retries: it checks the
initial pager/Close geometry before clicks, stable pagination while the table
scrolls, 50-row pages, complete-dataset search and confirmations. Four added
cases also verify that late clipboard success/failure from closed details does
not show feedback in another grant's details.

Recovery checks: Console/OAuth builds, type/UI source checks, 391 Console unit
tests, 107 built-in OAuth backend tests and 16 independently rerun setup/grant
behavior cases passed. The original candidate's complete CI passed on Python
3.11/3.12/3.13, with all five native and Compose PR jobs successful. Final-head
CI and tagged publication still require their own results; PR package checks
do not establish an issued release. This targeted correction does not claim a
new complete optional layout/visual run.

## Remaining limits

An initial unfiltered browser invocation stopped on two optional `@visual`
reset-layout cases at widths 390 and 1366: the table moved 2 px against a strict
less-than-2-px assertion. Those failures are preserved, not waived. The full
optional layout/visual suite was not executed and no baselines were regenerated;
the eight optional 0.4.0 failures are not newly reported passing. The standard
full behavior command excludes `@visual` according to the existing script.

Synthetic tests do not establish full real ChatGPT/provider compatibility,
public TLS/cookie/proxy behavior, production upgrades or uninterrupted sessions.
No real credentials, user proxies, SSH keys or tunnels were configured. The
production safe network executor remains absent; real Git acquisition, proxy
probes, tool preparation and configured network installs still fail closed.

Publishing must use the existing protected-main/release workflow. Five native
targets, Compose, two offline images, SPDX, digests, checksums and all-asset
provenance must finish and be checked before calling the release complete. The
published title/body must be read back and compared with the 0.4.1 source and
paired release notes. This source-validation record is not publication evidence.
