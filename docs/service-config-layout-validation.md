# Service configuration layout validation

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
