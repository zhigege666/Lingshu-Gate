# Tool argument policies

[简体中文](zh-CN/argument-policies.md) · [Documentation index](README.md)

An argument policy restricts a tool that the caller is already permitted to invoke. It never grants access. Policies are disabled by default, persist by tool ID and apply to REST, direct MCP, catalog, fixed-tool and grouped calls.

## Edit in the Console

With authenticated `grants.manage` permission, open **Tools → tool details → Argument policy**. Enable the policy, add conditions, optionally validate an example, and save. All enabled rules must match. Missing properties fail a condition, including equality with `null`.

| Operator | Example | Meaning |
|---|---|---|
| `equals` | `{"id":"tenant","pointer":"/tenant","operator":"equals","value":"example"}` | Exact JSON equality; `true` is not numeric `1` |
| `allowed_values` | `{"id":"region","pointer":"/region","operator":"allowed_values","values":["eu","us"]}` | Value equals one of at most 64 explicit candidates |
| `number_range` | `{"id":"size","pointer":"/limit","operator":"number_range","minimum":1,"maximum":50}` | Inclusive numeric bounds; numeric strings and booleans are rejected |
| `string_prefix` | `{"id":"prefix","pointer":"/path","operator":"string_prefix","prefix":"/approved/"}` | String begins with the given text |

Pointers use JSON Pointer: `/a~1b` selects key `a/b`, `/~0` selects `~`, and `/items/0` selects the first array element. Array indexes are canonical non-negative integers. The empty pointer selects the entire argument object.

A prefix rule is a string check. Use the tool's filesystem confinement for path security; a prefix alone does not resolve symlinks or prevent traversal.

The policy supports at most **64 rules**, **64 KiB** of rule JSON, **24 levels** and **8,192 nodes**. The editor rejects duplicate keys and values it cannot preserve accurately, including unsafe JavaScript integers; it retains entered text for correction. Large legal values use compact JSON when indentation would exceed the editing budget.

## Effective arguments and pure preview

Gate applies explicit first-party argument preparation, including the tool's known defaults and existing type normalization. It does not guess defaults for unknown MCP tools. At actual dispatch, policy evaluation uses the same owned argument object as execution. After file-reference conversion, lock waits and any permitted read retry, Gate rechecks current identity, authority, definition and policy.

**Validate example** does not execute a tool or save the draft. A `fileRef` requires the real runtime's owner/target-bound conversion to `filePath`; preview reports `argument_policy_preview_requires_runtime` instead of claiming it has validated that execution. A successful example is not a promise that later runtime authorization or arguments will remain unchanged.

If a save conflicts or its result is unknown, read the current policy before saving again. The Console keeps the draft while refreshing, displays a persistent refresh requirement, and requires review of the current revision. Clearing or validating an example does not resolve an unknown save. Closing with unsaved rules or example text asks before discarding it.

## API and audit

| Method and path | Operation |
|---|---|
| `GET /v1/tools/{tool_id}/argument-policy` | Read current enabled state, rules and revision |
| `POST /v1/tools/{tool_id}/argument-policy/preview` | Validate a draft and example without invocation |
| `POST /v1/tools/{tool_id}/argument-policy/csrf?request_digest=<SHA-256>` | Get a session confirmation bound to the exact PUT body |
| `PUT /v1/tools/{tool_id}/argument-policy` | Save `expected_revision`, `enabled` and `rules` |

Console writes require same-origin session confirmation; the digest covers the **exact UTF-8 request bytes**, not a separately reserialized JSON object. Permission checks also apply to API-token writes and their scope/delegation ceilings. Saves use a revision compare-and-swap and an atomic audit; an audit failure rolls back the policy.

Denied policy calls record stable rule ID, pointer, policy revision and reason, without input/output values. A denial before execution is `not_invoked`. If a first read attempt already reached a downstream and the retry is denied, the audit preserves that attempt and reports an error; it must not claim nothing ran.

Policies survive temporary tool disappearance. A corrupt stored policy fails closed. Upgrades add migration `0023_tool_argument_policy`; an older Gate binary does not enforce this policy even if it can open the database. Follow the [upgrade procedure](deployment.md) and retain a consistent backup.
