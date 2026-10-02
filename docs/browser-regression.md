# Browser regression

[简体中文](zh-CN/browser-regression.md)

The browser suite uses Playwright and the built Console served by a real, loopback-only Gate. Each run creates a new temporary directory and SQLite database, clears inherited `LINGSHU_GATE_*` settings, and creates synthetic administrator/viewer accounts. A single in-process synthetic MCP tool is registered, classified, published and granted to the fixture viewer for real draft authorization checks; it opens no downstream connection. It never attaches to an existing server. No production credentials, external downstream connections, or tunnels are needed. The delivery case starts only its reviewed synthetic local stdio process; the recovery case runs a dependency-free local Node build that intentionally fails once. The remote case uses a synthetic loopback HTTP peer started by the fixture on a dynamically assigned port. The fixed loopback port is 18763; a collision fails instead of reusing an unknown service.

## Run

From the repository root, after installing the normal frozen Python dependencies:

```bash
npm --prefix web ci
npm --prefix web run build
cd web
npx playwright install chromium
cd ..
timeout 180 npm --prefix web run e2e:smoke
timeout 300 npm --prefix web run e2e:full
timeout 180 npm --prefix web run e2e:permissions
timeout 180 npm --prefix web run e2e:large-data
timeout 180 npm --prefix web run e2e:visual
timeout 120 .venv/bin/pytest -q tests/test_personal_access_contract.py tests/test_viewer_permissions.py tests/test_user_downstream_credentials.py tests/test_delegated_access_scope.py
```

An installed compatible Chromium can be selected with `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium`. CI uses Playwright's pinned browser. The checked-in Linux visual baselines were generated with system Chromium 151.0.7922.173; use the same runtime for visual comparison or review platform-specific regeneration. Python comes from `.venv/bin/python`. Rebuild after frontend changes; the suite deliberately does not silently build or reuse a development server. Each test has a 30-second deadline (60 seconds for the real delivery journey), startup has a 30-second deadline, and the fixture process has a final 30-minute lifetime cap. Inspect progress every 30 seconds; if there is no output for 60 seconds, inspect processes/logs and terminate before retrying. Do not remove timeouts to mask a stuck run.

## Scenarios and evidence

| ID | Layer | Contract |
|---|---|---|
| E2E-001 | Real browser/API | Short-screen login, associated input labels, keyboard submission, main action inside viewport and unobscured |
| E2E-002 | Real browser/API | Viewer cannot read service/config/credential/build/upload control-plane APIs; own token metadata remains available |
| E2E-003 | Real browser/API | Failed login can recover with a subsequent valid submission |
| E2E-004 | Real browser/API | Personal service summaries and self-only invocation routes, without management API access |
| E2E-005 | Real browser/API | 390×844 narrow-screen login and keyboard submission without horizontal overflow |
| E2E-006 | Real browser/API | Create a disabled personal grant for a seeded published tool, verify enabling is unavailable without trust and identity setup, reject cross-user access, cancel/revoke through UI |
| E2E-007 | Real browser/API/stdio | UI upload, explicit runtime/target persisted through the task draft, dependency-free build, edit/save delivery configuration, cancel unsaved navigation without writes, confirm deploy/start; real runtime discovery and invocation validate the marker and four task IDs |
| E2E-008 | Real browser/API/process | Deliberately fail the first synthetic build, then retry through the UI to a new successful build record; source code is not edited |
| E2E-009 | Real browser/API/HTTP | Create remote configuration, apply stopped, connect/discover, save/reconnect and invoke through the UI against a private synthetic loopback peer; no OAuth/ChatGPT connection |
| E2E-101 | Mock presentation | 5,000 tools; bounded rendered page; internal scrolling resets on pagination; first action remains visible |
| E2E-102 | Mock presentation | 5,000 classifications; at most 50 rows; review action inside viewport and unobscured |
| E2E-103 | Mock presentation | 200 credentials; at most 50 rendered rows |
| E2E-104 | Mock presentation | 100 services; bounded document height; primary action visible |
| E2E-110–124 | Mock presentation | 200 members; 60 roles/30 permission types; 2,000 grants; 1,000 builds/500 deployments/500 uploads; 200 credentials/bindings/audits/logs/events; 100 tokens/caches/configs; 200 disabled scope drafts; dashboard with 100 services |
| E2E-201–202 | Mock interaction | Cancel save without mutation; delayed save blocks duplicates; HTTP 200 with failed activation retains editor |
| E2E-203 | Mock interaction | Late service detail response cannot replace the current personal-service selection |
| E2E-204 | Mock interaction | Cancel both native Back and Forward; retain mounted unsaved configuration and accepted URL |
| E2E-301 | Visual | Desktop short-screen and narrow-screen login screenshot baselines |

Presentation tests intercept only listed GET responses after a real login. They do **not** establish authorization, upstream invocation, deployment success, or runtime readiness. Deterministic fixtures live in `web/e2e/synthetic-data.ts`. The viewport assertion checks the full rectangle and three hit-test points without scrolling; Playwright `visible` or auto-scrolling `click` alone is insufficient evidence.

Failures retain screenshots and traces under `web/test-results/`, with a report in `web/playwright-report/`; these generated paths are ignored by Git. Both may contain synthetic credentials and cookies, so only run against the fixture. CI retains failure artifacts for three days. Never point this harness at production or upload production traces.

## Layout and operational context

Run the page-level context and operational cases separately with:

```bash
timeout 180 npm --prefix web run e2e:full -- --grep '@list-context|@operations'
GATE_LAYOUT_EVIDENCE_DIR=../qa/layout GATE_LAYOUT_ASSERT=1 timeout 180 npm --prefix web run e2e:full -- --grep @layout-evidence
```

E2E-401–411 check each named list: configurations, shared credentials, cache, members, roles, grants, classifications, audit, tokens, builds and deployments. They exercise middle/end scrolling, visible headers/search/pagination, filtering and page changes. E2E-412 checks cache filesystem-state presentation and cancellation without mutation; E2E-413–414 exercise the authorized MCP selector at desktop and phone widths. These are **mock presentation/API-response tests**, not authorization or filesystem-cleanup proof.

The opt-in layout collector writes viewport PNGs and geometry JSON for 2048×1222, 1366×768, 390×844 and 1280×600. Without `GATE_LAYOUT_ASSERT=1`, a successful capture means only that evidence was collected. With it, explicit geometry checks cover populated trend labels/ranking, maintenance-list scrolling and service header/tab context. The collector is skipped in ordinary runs unless an evidence directory is provided. Keep before/after directories separate; do not ship traces, cookies or authentication storage with screenshot evidence.

## Coverage limits

The full command means all currently implemented nonvisual browser scenarios, not all acceptance requirements. Run visual snapshots separately on the same browser/OS/font environment as their generation; changes require human review, never blind `--update-snapshots`. Real authorization matrices remain pytest evidence and must be reported separately. Recovery coverage includes deterministic build failure/retry, failed activation feedback and login recovery; it does not exhaust every deployment compensation failure. The delivery case captures Chinese UI and checks the centered preparation form, stacked desktop step/status labels, compact mobile progress, uploaded-project actions and final configuration field/footer at 1672×941, 1366×768 and 390×844. The 390×844 case also explicitly scrolls to the final advanced upload checkbox and verifies reachability, no obstruction and the fixed footer; this is separate from first-screen action visibility and is not complete phone journey acceptance. Remote MCP browser creation/reconnect uses only a synthetic loopback HTTP peer. External network interoperability, user-specific downstream authentication and ChatGPT/OAuth connectivity are not established by this test. Visual baselines require independent review. Do not report these as passed based on the scenarios above. Add targeted deterministic cases as the corresponding interfaces stabilize, then report unit, real API, mock browser, real browser and visual review outcomes separately.

### Build ownership and optional synthetic preview adapter

`build-ownership.spec.ts` adds E2E-501–506 at 1280×720: delayed refresh preserves the selected upload, deleting another build preserves context, dirty target switching supports cancel and restores the destination draft, pending preflight protects browser history, and rollback start options belong to the selected deployment (including two deployments of one build). These tests use the isolated backend only for login/static Console; business responses and mutations are deterministic mocks. They verify UI ownership, request bodies and confirmation semantics, not real build/rollback execution or permission enforcement.

```sh
cd web
timeout 120 env PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npx playwright test e2e/build-ownership.spec.ts
```

E2E-507 is opt-in because its adapter is a separate preview handoff artifact. It loads the actual `delivery-preview.ts` implementation and exercises upload metadata, build progression, manifest draft persistence, deployment preview cancellation (zero deploy requests), and confirmed synthetic start with consistent upload/build/deployment/server IDs. All business API calls are intercepted: unknown endpoints return 501, foreign origins are blocked, and there is no API fallback to the temporary Gate. Only static Console assets use the local server. The uploaded bytes are intentionally synthetic metadata, never unpacked or executed. This is synthetic interaction evidence, not authentication, process startup, MCP connectivity or production deployment evidence. Playwright's route bridge also handles native EventSource requests; this does not independently validate the handoff's separate fetch/EventSource installation shim.

```sh
cd web
timeout 120 env GATE_PREVIEW_ADAPTER_PATH=/absolute/path/to/delivery-preview.ts PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npx playwright test e2e/preview-adapter.spec.ts
```

Without `GATE_PREVIEW_ADAPTER_PATH`, E2E-507 is skipped. This stateful mutation adapter is separate from the GET-only presentation fixtures described above.

The E2E-507 shell fixtures explicitly report health `status: synthetic` and diagnostics `{ok:false, checks:[], summary:{synthetic:true, executed:false}}`; they do not assert actual machine health. Successful startup is the adapter's synthetic state only.

E2E-508–509 extend the same synthetic ownership fixture: editing target/start/overwrite/root and directly creating a build must first CAS-save the current options, then POST the build, then link its ID using the incremented draft revision without reverting the options. A 409 on the initial draft save must produce no build POST and retain the user's inputs and route. Run just these and the affected adapter journey with `npx playwright test e2e/build-ownership.spec.ts e2e/preview-adapter.spec.ts --grep 'E2E-50[789]'` (set the adapter path above to include 507). No actual build process runs in these scenarios.

E2E-510 retries a failed build from another upload while the initial older destination-draft response is delayed; it verifies destination options, no spurious pending-navigation dialog, and the next save using the newest revision. E2E-511 returns 409 only after build creation: the new build and current options remain visible, a specific context-save error is shown, and only one build POST occurs. These also use mocked business endpoints. Include `--grep 'E2E-(008|50[789]|51[01])'` across the ownership, adapter, and delivery-recovery specs for the affected six-case regression; 008 alone executes a real isolated synthetic build/retry.

E2E-520–522 are opt-in Chinese maintenance typography checks (1188×768, 1366×768, 390×844; 100 configurations, 100 cache entries, 200 credentials). `GATE_MAINTENANCE_EVIDENCE_DIR=/tmp/maintenance` captures initial/status-column/end screenshots and text-line geometry; add `GATE_MAINTENANCE_ASSERT=1` to require single-line short headers/status/actions, visible unobscured actions and the horizontally scrolled target column, no outer horizontal overflow, and no increase in pre-existing vertical overflow (measured by removing and restoring exactly the nine new CSS rules in the browser). Run `npx playwright test e2e/maintenance-nowrap.spec.ts`. Capture-only success is not layout acceptance; business data is synthetic and the login backend is isolated.

E2E-530–533 (`personal-layout.spec.ts`) are opt-in via `GATE_PERSONAL_LAYOUT_DIR=/tmp/personal-layout`, using 1188×761, 2048×1119, 1366×768 and 390×844. They check 0/1/41 authorized-service summaries (natural single-page height, no single-page paginator, real offset changes), 0/1-tool drawers' natural height and a 41-tool drawer's available space and reachable test action, service-title creation buttons and their actual navigation/dialog paths, and 5000-tool catalog/review scroll areas with visible pagination and page-change scroll reset. Business responses are synthetic; only login/static assets use the isolated backend. The fixture rejects any UI mutation during this read-only journey. These layout checks do not prove API authorization or external MCP connectivity.

E2E-540–541 (`log-tool-scope.spec.ts`, `GATE_LOG_TOOL_DIR=/tmp/log-tools`) exercise the scoped tool selector at 1188×761 and 390×844: no tool query under All MCPs, same-MCP preservation, MCP-change reset, empty/historical tools, exact-ID fallback, keyboard clearing, repeated reset, and explicit Apply semantics. Events intentionally has no tool filter. These are synthetic response/interaction checks; real scope authorization is covered separately by API tests.

E2E-550–553 (`remaining-panels.spec.ts`, `GATE_REMAINING_PANELS_DIR=/tmp/panels`) exercise 200 downstream credentials and personal grants, a below-fold 200-identity section, 500-upload history and 200 build-log lines at the four personal-layout sizes. They verify usable remaining height, actual scrolling, pagination and reachable actions. The first credential is synthetic Authorization Header / required / configured, followed by required missing and optional missing examples; no credential secret is present.

Set `GATE_LIST_LAYOUT_MATRIX=1` when running `list-context.spec.ts` to expand its 11 named pages into 33 cases at 2048×1119, 1366×768 and 390×844, with Chinese screenshots. The matrix preserves first/middle/end/filter/page assertions and checks first/last-row actions when present. Set output-directory variables only for intended opt-in cases; diagnostic-only captures are excluded with `--grep-invert diagnostic`. These suites validate layout and UI requests with synthetic business fixtures; they are not a rerun of the real authorization or build-process acceptance layers.

E2E-560–565 (`external-identity-layout.spec.ts`, `GATE_IDENTITY_EVIDENCE_DIR=/tmp/identity-ui`) separately check the configuration modal at2048×1119/1366×768/390×844, long user names with copyable IDs, multiple identity links to the same user, remote name/ID search and pagination, dirty cancellation without mutation, and absence of directory requests/UI without `external_connections.manage`. A custom identity with that capability but without `users.manage` is intentionally allowed by the dedicated endpoint contract. List/picker data and capability presentation are synthetic; they do not prove backend authorization. Run these opt-in scenarios separately from real API security tests.

E2E-570–574 (`personal-payload.spec.ts`, `GATE_PAYLOAD_EVIDENCE_DIR=/tmp/payload-ui`) cover retained payload presentation: `null`, `false`, `0`, the five recording statuses, JSON line search/expansion, full retained-content copy after a fresh detail GET, late responses after closing/switching, mocked403 clearing old content, and visible clipboard failure. The phone case uses390×844 and long synthetic JSON. These tests do not prove redaction completeness, authorization enforcement, retention expiry or recovery of unrecorded content; corresponding real API/cleanup tests remain separate evidence.

E2E-576–577 add copy-request ownership: a newer denied output copy must invalidate an older pending successful input copy without restoring content or writing the clipboard; administrator copy must retain visible success feedback. Both use synthetic detail responses. The personal drawer evidence collector now waits for the wrapper's animation to finish and three stable animation-frame rectangles before 0/1/many-tool screenshots, then checks right-column visibility and hit targets.

E2E-580–583 (`retention-ui.spec.ts`, `GATE_RETENTION_EVIDENCE_DIR=/tmp/retention-ui`) cover the390×844 policy footer, default7-day/metadata-only values, disabled-worker cleanup, shortened-policy preview/cancel/save, independent cleanup confirmation, explicitly manual job refresh/cancellation,409 draft preservation, late stale-preview rejection and absence of policy requests without capability. Every retention request is intercepted with synthetic state, including worker-enabled jobs. No real cleanup worker is enabled, no real records are deleted, and these checks do not replace backend policy/CAS/cleanup authorization tests.
