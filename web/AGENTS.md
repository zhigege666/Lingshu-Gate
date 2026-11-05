# Console UI instructions

These instructions supplement the repository root `AGENTS.md` for `web/`.

- Before changing Console UI, read [`docs/ui-interaction-contract.md`](../docs/ui-interaction-contract.md) ([简体中文](../docs/zh-CN/ui-interaction-contract.md)) and the nearest component, domain adapter, and tests.
- Apply the contract to new or migrated UI and affected consumers. It is an acceptance target, not a claim that existing pages already comply; do not rewrite unrelated pages merely to satisfy it.
- Use the existing shadcn/Radix components and the shadcn-admin layout direction for the Console shell, navigation, page actions and new shared controls. Retained Ant Design tables/editors use the same theme tokens. Reuse existing theme entry points; preserve domain authorization, validation, request ownership and secret lifecycles.
- Remove redundant task stages: ordinary MCP synchronization and tool use do not require review/publication; normal save, search and validation do not add confirmation dialogs. Keep one concrete impact confirmation for destructive operations, replacement of a running instance, actual authorization expansion or abandoning dirty work. Backend permission checks remain mandatory.
- Follow the centered Dialog and direct-choice supplement in the paired UI contract: new/edit/detail overlays use centered Dialogs, and 2–5 fixed short mutually exclusive choices use accessible radio controls. Preserve route pages and migrate existing drawers explicitly.
- Form labels and controls share one row: fixed-width labels on the left, controls on the right, with help/errors below the controls. Keep labels on one line in both languages. At narrow widths, collapse paired fields into individual rows instead of placing labels above inputs.
- Prioritize task completion, recoverable errors, and lossless editing. Keep page identity accessible and compact; do not add decorative headings, repeated explanations, or empty equal-height panels.
- Select evidence by the change's risk. Record source checks, behavior tests, browser evidence, and independent UI review separately; never describe an unexecuted check as passed.
- Run relevant existing checks from the repository root: `npm --prefix web run check`, `npm --prefix web test`, `npm --prefix web run build`, and `git diff --check`. For documentation-only changes, check links, English/Chinese parity, and whitespace. `check:ux` is a source check, not a browser UI acceptance test.
