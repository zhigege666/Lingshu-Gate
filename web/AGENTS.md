# Console UI instructions

These instructions supplement the repository root `AGENTS.md` for `web/`.

- Before changing Console UI, read [`docs/ui-interaction-contract.md`](../docs/ui-interaction-contract.md) ([简体中文](../docs/zh-CN/ui-interaction-contract.md)) and the nearest component, domain adapter, and tests.
- Apply the contract to new or migrated UI and affected consumers. It is an acceptance target, not a claim that existing pages already comply; do not rewrite unrelated pages merely to satisfy it.
- Keep Ant Design as the primary component library. Reuse existing theme entry points and interaction components; preserve domain-specific authorization, confirmation, validation, and secret lifecycles.
- Prioritize task completion, recoverable errors, and lossless editing. Keep page identity accessible and compact; do not add decorative headings, repeated explanations, or empty equal-height panels.
- Select evidence by the change's risk. Record source checks, behavior tests, browser evidence, and independent UI review separately; never describe an unexecuted check as passed.
- Run relevant existing checks from the repository root: `npm --prefix web run check`, `npm --prefix web test`, `npm --prefix web run build`, and `git diff --check`. For documentation-only changes, check links, English/Chinese parity, and whitespace. `check:ux` is a source check, not a browser UI acceptance test.
