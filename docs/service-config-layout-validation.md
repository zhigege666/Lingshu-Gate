# Service configuration layout validation

## Delivery candidate and focus regressions

The tested product and browser sources are `a0cc7925f02718e44cb0216e82581eff9b7644fc`. The candidate incorporates main `2cbbe0673ce221a490af55d7d45abb5171552ec6`; both README files are byte-identical to that main revision. The sections below describe earlier, source-bound stages and retain their original evidence.

Delivery configuration now restores the original action after saving. Service configuration remembers the portaled footer control before asynchronous precheck disables it, so cancelling confirmation preserves both the draft and focus. When a successful save refreshes and replaces the original Edit button, closing the dialog finds the current visible Edit action. A removed, disabled or hidden trigger, or a BODY/HTML focus snapshot from the asynchronous **Edit and enable** entry, uses the current configuration action or active service entry.

Fresh type/UX checks, 75 frontend test files containing **455 tests**, Console/OAuth builds, version consistency and whitespace checks passed. The complete original two-file browser scope plus ten permanent focus regressions passed **59/59**, with no retries, skips or flaky cases. This includes the existing English/Chinese, light/dark, desktop Form/JSON matrix. The eight additional refresh, invalid-trigger and asynchronous-entry cases assert the actual focused element after 250ms; all returned to a button. Save checks retain exactly one PUT, the configuration digest, and false apply/start intent.

The first six-case attempt failed during background-button lookup and is retained as a harness failure. After correcting only that lookup, unchanged product `281d3a7` failed six focus assertions with BODY active. The identical test file then passed on `762caac`. Two further asynchronous-entry cases failed with BODY active on unchanged product `762caac`; the identical expanded test file passed on `a0cc792`. These are two separately bound red/green comparisons, not one combined same-file claim.

Independent code review at exact `a0cc792` closed both additional P2 findings and found no unhandled P1/P2 within the reviewed focus scope. It independently verified the 59/455 execution records, eight raw focus attachments and red/green test bytes; the reviewer did not rerun those suites. The earlier independent visual review viewed all 34 final captures from `281d3a7` in its covered layout and original focus scope; it does not constitute a new screenshot review of `a0cc792`. New screenshots and raw browser records remain in the original cloud executor. No new image content is committed or transferred.

**The candidate is not merge-ready.** The unchanged repository identity checker, run with `--history` against all 17 current published heads, all 17 tags and the candidate, fails two `TXT-045` findings in historical commit `e0766101fa344db399122884aadbb08ac4b8f439`. They are in the earlier release-evidence branch, outside this candidate's ancestry. The initial worker scan has the same findings; a fresh remote inventory corrected a stale local remote-tracking assumption. Identity policy and frozen evidence are unchanged, and the unique evidence branch is preserved. Hosted CI, merge and a subsequent release remain gated by this failure.

[Text-only delivery evidence](benchmarks/gate-service-modal-delivery-a0cc792.json) records exact product/test blobs, raw-log and report hashes, actual red/green results and the identity failure. Backend suites, packaging, a new release and real nx5/Podman acceptance have not been rerun for this candidate. API permissions, version and release workflows are unchanged.

## Contract follow-up after independent code review

The comparison images and 70e3b08 implementation below are retained as historical evidence. Current implementation `77b1a8d348764528742fefa53e78117631de381a` supersedes the inline switch-help placement: it uses the existing Field description **below** the switch, as required by the unchanged UI contract.

ConfigsPage now opts into existing confirmation focus restoration. New/Edit close and Keep editing have direct browser regressions; a removed or disabled Edit trigger returns to the available New Config action. The third consumer, DeliveryConfigEditor, is exercised through the actual BuildsPage at all four desktop sizes in both languages, including draft retention and exactly one draft-save PUT with start/overwrite remaining false.

The final checks passed: 455 frontend tests, type/UX checks, Console/OAuth build and 49 browser cases with no retries. [Text-only follow-up evidence](benchmarks/gate-service-modal-contract-followup-77b1a8d.json) records source blobs, negative controls and local screenshot metadata. All 23 new PNGs remain in the original cloud environment, with no new images committed, uploaded or transferred; the prior screenshot history is unchanged. New-source incremental code review and visual acceptance remain pending.


This isolated change aligns the existing **Service configurations → Edit** form. The four Chinese desktop comparisons use the actual built Console with synthetic API fixtures. Independent review by dot/the parent and acceptance on a real remote deployment remain **pending**.

| Source | Exact revision |
| --- | --- |
| Baseline main | `45cec40c1e57d7290ab249e620b5a50fa939e115` |
| Implementation | `70e3b08c219b738dbee2551cb88407f0d758a634` |
| Branch | `fix/gate-service-modal-alignment-20261010` |

The baseline used **136px** labels for paired fields and **272px** labels for full rows. Their first-column controls differed by **136px** at every tested desktop size. Startup rows combined a 272px label with a half-width column, leaving only **111px** for the switch/help. This was a conflict between fixed grid tracks; the percentage-width hypothesis was not confirmed.

The form now uses one fixed label track per language (Chinese **160px**, English **272px**). Paired fields collapse when the container is too narrow. Enabled/startup controls have separate aligned rows and readable help. The existing 860px editor frame, title, padding and footer remain; the shared 1200px service dialog retains its frame. A separate pre-existing discard-focus failure was reproduced against the untouched baseline and repaired locally by restoring focus to the connected New/Edit trigger.

## Actual desktop comparisons

Each image is the full viewport, captured from Chromium with animations disabled. The service ID, runtime mode, enabled/startup controls, endpoint, timeout and headers are shown in the same external-HTTP editing state. All paths, names and responses are synthetic. The user's original private screenshot is not republished.

| Viewport | Before | After | First-column control spread |
| --- | --- | --- | --- |
| 2560×1080 | ![Before 2560×1080](benchmarks/gate-service-modal-alignment-70e3b08/before-external-zh-2560x1080.png) | ![After 2560×1080](benchmarks/gate-service-modal-alignment-70e3b08/after-external-zh-2560x1080.png) | 136px → 0px |
| 1920×1080 | ![Before 1920×1080](benchmarks/gate-service-modal-alignment-70e3b08/before-external-zh-1920x1080.png) | ![After 1920×1080](benchmarks/gate-service-modal-alignment-70e3b08/after-external-zh-1920x1080.png) | 136px → 0px |
| 2560×1440 | ![Before 2560×1440](benchmarks/gate-service-modal-alignment-70e3b08/before-external-zh-2560x1440.png) | ![After 2560×1440](benchmarks/gate-service-modal-alignment-70e3b08/after-external-zh-2560x1440.png) | 136px → 0px |
| 1600×900 | ![Before 1600×900](benchmarks/gate-service-modal-alignment-70e3b08/before-external-zh-1600x900.png) | ![After 1600×900](benchmarks/gate-service-modal-alignment-70e3b08/after-external-zh-1600x900.png) | 136px → 0px |

The author inspected these pairs: control starts now align, the switch descriptions have room, labels stay on one line, and the save footer is visible. DOM geometry reports no horizontal overflow or label overflow. English at 1600×900 uses individual ID/name rows to preserve the long startup label.

## Modes, errors and keyboard

| Actual 1600×900 capture | What it shows |
| --- | --- |
| [Managed Stdio](benchmarks/gate-service-modal-alignment-70e3b08/after-managed-stdio-zh-1600x900.png) | Command/cwd fields and aligned startup controls. |
| [Managed HTTP](benchmarks/gate-service-modal-alignment-70e3b08/after-managed-http-zh-1600x900.png) | Additional endpoint fields with a reachable footer. |
| [Long error, advanced fields, focused endpoint](benchmarks/gate-service-modal-alignment-70e3b08/after-long-error-advanced-focused-zh-1600x900.png) | Replaced long URL, wrapped synthetic validation error, focus ring and reachable footer; the body can scroll. |
| [English external HTTP](benchmarks/gate-service-modal-alignment-70e3b08/after-external-en-1600x900.png) | One-line labels, readable switch help and visible save action. |

Browser actions passed for all three runtime modes, replacing the endpoint, opening advanced settings, validation-summary focus, Space on the enabled switch, arrow navigation in runtime choices, Tab from Cancel to Save, and focus return after confirming draft discard. Existing tests preserve save/apply/start, permissions, masked endpoints and lossless Form/JSON editing.

## Checks and boundaries

| Executed check | Result |
| --- | --- |
| Frontend type and UX source checks | Passed, exit 0. |
| Frontend unit tests | 75 files, 455 tests passed, exit 0. |
| Console and OAuth web build | Passed, exit 0. |
| Actual Playwright suite | 34 passed: 7 new checks and 27 existing configuration checks, exit 0; no retries. |
| Baseline captures | Four passed; two after-only checks skipped in the baseline capture script. |
| Baseline focus negative control | Expected failure; the unchanged frontend did not return focus to Edit. The final frontend passes. |
| Whitespace/source boundary | `git diff --check` passed; no version or permission changes. |

The existing configuration suite includes automated form/JSON checks at all four desktop sizes in English/Chinese and light/dark themes (16 matrix cases). They cover the second, shared 1200px dialog and are recorded separately from the primary 860px comparison; not every matrix screenshot has received manual review.

The environment was the original saved Linux cloud executor (Node 24.19.0, npm 11.9.0, Chromium 151.0.7922.173, Playwright 1.63.0, Vite 8.3.2). An isolated loopback server rendered the built application; API configurations and validation results were synthetic. No real service or remote-host configuration was changed.

[Machine-readable evidence](benchmarks/gate-service-modal-alignment-70e3b08/validation.json) binds the source blobs, 12 screenshots, geometry, command outcomes and raw-log hashes. Command paths are normalized to repository-relative equivalents; raw logs stay private.

This UI branch has not been merged, tagged or released. The immutable v0.4.7 assets retain their original source. Backend/packaging and real nx5/Podman checks were not rerun for this presentation/focus change. **Independent design review and real remote visual acceptance remain pending.**

[简体中文](zh-CN/service-config-layout-validation.md)
