import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react"
import { Alert, Button, Input, Radio, Switch } from "antd"
import { argumentPolicyApi, ArgumentPolicyRequestError, type ArgumentPolicy, type ArgumentPreview } from "@/api/argument-policy"
import type { ToolDefinition } from "@/api/client"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import type { Locale, TFunction } from "@/i18n"
import { parsePolicyJson, PolicyJsonError } from "./json"
import { newRule, policyDraft, validatePolicyDraft, type PolicyIssue, type RuleDraft } from "./model"
import "./policy-dialog.css"

function issueText(code: string, zh: boolean): string {
  const messages: Record<string, [string, string]> = {
    json_syntax: ["输入有效的 JSON；字符串要加双引号。", "Enter valid JSON; quote string values."],
    json_duplicate: ["JSON 字段名重复，请保留明确的单个值。", "A JSON member is duplicated. Keep one explicit value."],
    json_number: ["此数字不能由浏览器安全保留，请通过 API 设置或输入可准确表示的数字。", "The browser cannot preserve this number. Use the API or enter an exactly representable number."],
    json_unicode: ["请输入完整的 Unicode 字符。", "Enter complete Unicode characters."],
    json_limit: ["JSON 超出大小或节点数量限制。", "JSON exceeds the size or node limit."],
    json_depth: ["JSON 嵌套过深，请减少层数。", "JSON is nested too deeply. Reduce its depth."],
    rule_id: ["ID 必须唯一，以字母或数字开头，最多 64 位，仅含字母、数字、下划线或连字符。", "Use a unique ID of 1–64 letters, digits, underscores or hyphens, starting with a letter or digit."],
    pointer: ["使用 JSON Pointer，如 /limit。空值表示整个参数对象；~ 和 / 分别写成 ~0 和 ~1。", "Use a JSON Pointer such as /limit. Empty selects the argument object; escape ~ as ~0 and / as ~1."],
    allowed_values: ["输入包含 1～64 个值的 JSON 数组。", "Enter a JSON array containing 1–64 values."],
    range_required: ["至少填写一个边界。", "Enter at least one bound."],
    range_number: ["请输入数字，不要使用字符串、布尔值或 null。", "Enter a number, without quotes, booleans or null."],
    range_order: ["最大值必须大于或等于最小值。", "Maximum must be greater than or equal to minimum."],
    prefix: ["前缀长度为 1～1024 个字符。", "Use a prefix of 1–1,024 characters."],
    policy_limit: ["最多 64 条规则，规则合计不超过 64 KiB。", "Use at most 64 rules, totalling no more than 64 KiB."],
    object_required: ["示例参数必须是 JSON 对象。", "Example arguments must be a JSON object."],
  }
  return (messages[code] || messages.json_syntax)[zh ? 0 : 1]
}

export function ArgumentPolicyDialog({ tool, locale, t, onClose }: {
  tool: ToolDefinition; locale: Locale; t: TFunction; onClose: () => void
}) {
  const zh = locale === "zh-CN", prefix = useId()
  const [saved, setSaved] = useState<ArgumentPolicy | null>(null)
  const [enabled, setEnabled] = useState(false), [rows, setRows] = useState<RuleDraft[]>([])
  const [baseline, setBaseline] = useState(""), [example, setExample] = useState("{}")
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null)
  const [refreshRequired, setRefreshRequired] = useState(false), [status, setStatus] = useState<string | null>(null)
  const [preview, setPreview] = useState<ArgumentPreview | null>(null), [exampleOpen, setExampleOpen] = useState(false)
  const [touched, setTouched] = useState<Set<string>>(new Set()), [submitted, setSubmitted] = useState(false)
  const [exampleAttempted, setExampleAttempted] = useState(false), [revision, setRevision] = useState(0)
  const generation = useRef(0), controller = useRef<AbortController | null>(null), pending = useRef(false), nextKey = useRef(1)
  const language = useRef(zh); language.current = zh
  const { confirm, confirmDialog } = useConfirm(t, true)
  const draftKey = JSON.stringify({ enabled, rows })
  const policyDirty = saved !== null && draftKey !== baseline
  const dirty = policyDirty || example !== "{}"
  const validation = validatePolicyDraft(enabled, rows, saved?.revision ?? 0, revision)
  const visibleIssues = validation.issues.filter(issue => submitted || issue.immediate || touched.has(issue.index + ":" + issue.field))
  const fieldId = (index: number, field: string) => prefix + "-" + index + "-" + field
  let exampleError: string | null = null, exampleValue: Record<string, unknown> | null = null
  try {
    const value = parsePolicyJson(example, 1_048_576)
    if (!value || Array.isArray(value) || typeof value !== "object") exampleError = "object_required"
    else exampleValue = value as Record<string, unknown>
  } catch (cause) { exampleError = cause instanceof PolicyJsonError ? cause.code : "json_syntax" }
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose })

  const load = useCallback(async (preserve = false) => {
    const current = ++generation.current
    controller.current?.abort()
    const abort = new AbortController(); controller.current = abort
    pending.current = true; setBusy(true); setError(null); setStatus(null); setPreview(null)
    try {
      const result = await argumentPolicyApi.get(tool.id, abort.signal)
      const next = policyDraft(result)
      if (generation.current !== current) return
      setSaved(result); setBaseline(JSON.stringify({ enabled: result.enabled, rows: next }))
      if (!preserve) { setEnabled(result.enabled); setRows(next); setSubmitted(false); setTouched(new Set()) }
      setRefreshRequired(false)
      if (preserve) setStatus(language.current ? "已读取当前版本，尚未保存的草稿已保留。请核对后保存。" : "Current revision loaded; your unsaved draft is preserved. Review it before saving.")
    } catch (cause) {
      if (generation.current !== current) return
      const unsupported = cause instanceof PolicyJsonError || cause instanceof Error && cause.message === "policy_editor_unsupported"
      setError(unsupported ? language.current ? "该策略含本编辑器无法安全表示的值或字段，请通过 API 查看和修改。" : "This policy contains values or fields the editor cannot safely represent. Review and edit it through the API."
        : language.current ? "读取失败，请检查会话或管理权限后重试。" : "Unable to load. Check your session or management permission and retry.")
      setRefreshRequired(true)
    } finally { if (generation.current === current) { pending.current = false; setBusy(false) } }
  }, [tool.id])

  useEffect(() => { void load(); return () => { generation.current++; controller.current?.abort(); pending.current = false } }, [load])

  function changed() { setRevision(value => value + 1); setPreview(null); setStatus(null) }
  function updateRow(index: number, patch: Partial<RuleDraft>) {
    if (pending.current) return
    setRows(values => values.map((row, position) => position === index ? { ...row, ...patch } : row)); changed()
  }
  function locate(issue: PolicyIssue) {
    document.getElementById(fieldId(issue.index, issue.field))?.focus()
  }
  async function save() {
    if (pending.current || !saved || !policyDirty || refreshRequired) return
    setSubmitted(true)
    if (validation.issues.length) { locate(validation.issues[0]); return }
    pending.current = true; setBusy(true); setError(null); setStatus(null)
    const current = generation.current, abort = new AbortController(); controller.current = abort
    const submittedBody = validation.body
    try {
      const result = await argumentPolicyApi.save(tool.id, submittedBody, abort.signal)
      const next = policyDraft(result)
      if (generation.current !== current) return
      setSaved(result); setEnabled(result.enabled); setRows(next); setBaseline(JSON.stringify({ enabled: result.enabled, rows: next }))
      setSubmitted(false); setTouched(new Set()); setPreview(null); setRefreshRequired(false)
      setStatus(language.current ? "参数限制已保存。" : "Argument limits saved.")
    } catch (cause) {
      if (generation.current !== current) return
      const conflict = cause instanceof ArgumentPolicyRequestError && cause.code === "argument_policy_revision_conflict"
      setError(conflict ? language.current ? "策略已被其他操作更新。刷新会保留草稿，请核对当前版本后再保存。" : "Another operation updated this policy. Refresh preserves your draft; review the current revision before saving."
        : language.current ? "保存未确认。草稿已保留，请刷新核对服务器状态后再操作。" : "Save was not confirmed. Your draft is preserved; refresh to check server state before another write.")
      setRefreshRequired(true)
    } finally { if (generation.current === current) { pending.current = false; setBusy(false) } }
  }
  async function checkExample() {
    if (pending.current || !saved) return
    setSubmitted(true); setExampleAttempted(true); setPreview(null); setError(null)
    if (validation.issues.length) { locate(validation.issues[0]); return }
    if (!exampleValue) { document.getElementById(prefix + "-example")?.focus(); return }
    pending.current = true; setBusy(true)
    const current = generation.current, abort = new AbortController(); controller.current = abort
    try {
      const result = await argumentPolicyApi.preview(tool.id, validation.body, exampleValue, abort.signal)
      if (generation.current === current) setPreview(result)
    } catch (cause) {
      if (generation.current !== current) return
      const needsRuntime = cause instanceof ArgumentPolicyRequestError && cause.code === "argument_policy_preview_requires_runtime"
      setError(needsRuntime ? language.current ? "fileRef 需要调用用户的运行时解析。此处未执行工具，请填写已解析的 filePath 示例。" : "fileRef needs the calling user's runtime resolution. No tool was invoked; use a resolved filePath in this example."
        : language.current ? "示例未通过工具参数校验或当前会话无权校验，请检查输入后重试。工具未执行。" : "The example failed tool-input validation or your session cannot validate it. Check the input and retry. No tool was invoked.")
    } finally { if (generation.current === current) { pending.current = false; setBusy(false) } }
  }

  const locked = busy || saved === null
  const touch = (index: number, field: string) => setTouched(previous => new Set(previous).add(index + ":" + field))
  function rowField(index: number, field: string, label: string, control: ReactNode, help?: string) {
    const issue = visibleIssues.find(item => item.index === index && item.field === field)
    return <div className="argument-policy-row"><label htmlFor={fieldId(index, field)}>{label}</label><div className="min-w-0">
      {control}{help && <p className="mt-1 text-xs text-muted-foreground">{help}</p>}
      {issue && <p role="alert" id={fieldId(index, field) + "-error"} className="mt-1 text-sm text-destructive">{issueText(issue.code, zh)}</p>}
    </div></div>
  }
  function textInput(index: number, field: "id" | "pointer" | "prefix" | "minimum" | "maximum", maxLength: number, numeric = false) {
    const issue = visibleIssues.some(item => item.index === index && item.field === field)
    return <Input id={fieldId(index, field)} value={rows[index][field]} maxLength={maxLength} disabled={locked} status={issue ? "error" : undefined}
      aria-invalid={issue} aria-describedby={issue ? fieldId(index, field) + "-error" : undefined} inputMode={numeric ? "decimal" : undefined}
      onChange={event => updateRow(index, { [field]: event.target.value })} onBlur={() => touch(index, field)} />
  }
  function jsonInput(index: number, field: "value" | "values") {
    const issue = visibleIssues.some(item => item.index === index && item.field === field)
    return <Input.TextArea id={fieldId(index, field)} value={rows[index][field]} maxLength={65_536} disabled={locked} autoSize={{ minRows: 2, maxRows: 8 }}
      status={issue ? "error" : undefined} aria-invalid={issue} aria-describedby={issue ? fieldId(index, field) + "-error" : undefined}
      onChange={event => updateRow(index, { [field]: event.target.value })} onBlur={() => touch(index, field)} />
  }

  return <><FormDialog open title={zh ? "参数限制" : "Argument limits"} description={tool.name || tool.id} closeLabel={t("close")} onClose={() => void close()}
    dirty={dirty} pending={busy} error={error} className="sm:max-w-4xl" bodyClassName="space-y-4"
    onCloseAutoFocus={event => { event.preventDefault(); requestAnimationFrame(() => document.getElementById("tool-argument-policy-action")?.focus()) }}
    footer={<><Button disabled={busy} onClick={() => void close()}>{t("close")}</Button><Button disabled={busy} onClick={() => void load(policyDirty)}>{zh ? "刷新当前版本" : "Refresh current revision"}</Button>
      <Button type="primary" disabled={busy || !policyDirty || refreshRequired || !saved} onClick={() => void save()}>{t("save")}</Button></>}>
    <p className="text-sm text-muted-foreground">{zh ? "所有规则同时满足才允许调用。限制在实际调用前检查，不增加调用权限。关闭时不施加额外限制。" : "Every rule must match before a call is allowed. Limits are checked immediately before dispatch and do not grant access. Turning them off adds no restrictions."}</p>
    {busy && !saved && <p role="status">{t("loadingData")}</p>}
    {refreshRequired && saved && <Alert type="warning" showIcon title={zh ? "保存前必须刷新并核对当前版本；示例校验不会解除此状态。" : "Refresh and review the current revision before saving; example validation does not clear this requirement."} />}
    <div className="argument-policy-row"><label htmlFor={prefix + "-enabled"}>{zh ? "启用限制" : "Enable limits"}</label>
      <div className="flex flex-wrap items-center gap-3"><Switch id={prefix + "-enabled"} checked={enabled} disabled={locked} onChange={value => { setEnabled(value); changed() }} />
        <span className="text-xs text-muted-foreground">{saved ? (zh ? "当前版本 " : "Current revision ") + saved.revision : ""}</span></div></div>
    <p className="text-xs break-all text-muted-foreground">{tool.id}</p>
    {rows.length === 0 && saved && <p className="text-sm">{zh ? "尚未设置规则。添加规则以限制参数值。" : "No rules are configured. Add a rule to restrict argument values."}</p>}
    {rows.map((row, index) => <fieldset key={row.key} className="argument-policy-rule">
      <legend>{(zh ? "规则 " : "Rule ") + (index + 1)}</legend>
      <div className="flex justify-end"><Button size="small" disabled={locked} danger aria-label={(zh ? "移除规则 " : "Remove rule ") + (index + 1)} onClick={() => { setRows(values => values.filter((_, i) => i !== index)); setTouched(new Set()); changed() }}>{zh ? "移除" : "Remove"}</Button></div>
      {rowField(index, "id", zh ? "规则 ID" : "Rule ID", textInput(index, "id", 64))}
      {rowField(index, "pointer", zh ? "参数路径" : "Argument path", textInput(index, "pointer", 512), zh ? "JSON Pointer，如 /limit 或 /options/mode；留空表示整个参数对象。" : "JSON Pointer, such as /limit or /options/mode; empty selects the whole argument object.")}
      <div className="argument-policy-row"><label id={fieldId(index, "operator")}>{zh ? "匹配条件" : "Condition"}</label>
        <Radio.Group aria-labelledby={fieldId(index, "operator")} value={row.operator} disabled={locked} onChange={event => updateRow(index, { operator: event.target.value })} className="argument-policy-operators">
          <Radio value="equals">{zh ? "等于" : "Equals"}</Radio><Radio value="allowed_values">{zh ? "允许值" : "Allowed values"}</Radio>
          <Radio value="number_range">{zh ? "数字范围" : "Number range"}</Radio><Radio value="string_prefix">{zh ? "文本前缀" : "Text prefix"}</Radio>
        </Radio.Group></div>
      {row.operator === "equals" && rowField(index, "value", zh ? "匹配值" : "Value", jsonInput(index, "value"), zh ? "JSON 值：字符串、数字、布尔值、null、对象或数组。" : "A JSON value: string, number, boolean, null, object or array.")}
      {row.operator === "allowed_values" && rowField(index, "values", zh ? "允许的值" : "Allowed values", jsonInput(index, "values"), zh ? 'JSON 数组，例如 ["safe", "read"]。' : 'A JSON array, for example ["safe", "read"].')}
      {row.operator === "number_range" && <>{rowField(index, "minimum", zh ? "最小值" : "Minimum", textInput(index, "minimum", 100, true), zh ? "含边界；留空不设最小值。" : "Inclusive; empty means no minimum.")}
        {rowField(index, "maximum", zh ? "最大值" : "Maximum", textInput(index, "maximum", 100, true), zh ? "含边界；留空不设最大值。" : "Inclusive; empty means no maximum.")}</>}
      {row.operator === "string_prefix" && rowField(index, "prefix", zh ? "文本前缀" : "Text prefix", textInput(index, "prefix", 1024), zh ? "按字符匹配前缀，不构成文件系统沙箱。" : "Matches a text prefix; it does not provide a filesystem sandbox.")}
    </fieldset>)}
    <Button disabled={locked || rows.length >= 64} onClick={() => {
      let key: string
      do { key = "rule_" + nextKey.current++ } while (rows.some(row => row.id === key || row.key === key))
      setRows(values => [...values, newRule(key)]); changed()
    }}>{zh ? "添加规则" : "Add rule"} ({rows.length}/64)</Button>
    {visibleIssues.length > 0 && <Alert type="error" showIcon title={zh ? "请修正以下字段" : "Correct these fields"} description={<ul className="space-y-1">
      {visibleIssues.map((issue, index) => <li key={index}>{issue.index >= 0 ? <button type="button" className="text-left underline" onClick={() => locate(issue)}>
        {issue.path + " · " + issueText(issue.code, zh)}</button> : issueText(issue.code, zh)}</li>)}</ul>} />}
    <details open={exampleOpen} onToggle={event => setExampleOpen(event.currentTarget.open)} className="border-t pt-3">
      <summary className="cursor-pointer text-sm font-medium">{zh ? "校验示例参数" : "Validate example arguments"}</summary>
      <div className="mt-3 space-y-3">
        <p className="text-xs text-muted-foreground">{zh ? "仅校验当前草稿和工具参数格式，不调用工具。第一方工具会补齐已知默认值；未知上游工具不会推测默认值。输入仅保留在当前窗口。" : "Checks this draft and tool-input format without invoking a tool. Known first-party defaults are prepared; unknown upstream defaults are not inferred. Input stays in this dialog."}</p>
        <div className="argument-policy-row"><label htmlFor={prefix + "-example"}>{zh ? "示例参数" : "Example arguments"}</label><div>
          <Input.TextArea id={prefix + "-example"} value={example} maxLength={1_048_576} disabled={locked} autoSize={{ minRows: 3, maxRows: 10 }}
            aria-invalid={Boolean(exampleError && (exampleAttempted || example !== "{}"))}
            aria-describedby={exampleError && (exampleAttempted || example !== "{}") ? prefix + "-example-error" : undefined}
            status={exampleError && (exampleAttempted || example !== "{}") ? "error" : undefined} onChange={event => { setExample(event.target.value); setPreview(null); changed() }} />
          {exampleError && (exampleAttempted || example !== "{}") && <p role="alert" id={prefix + "-example-error"} className="mt-1 text-sm text-destructive">{issueText(exampleError, zh)}</p>}
        </div></div>
        <div className="flex flex-wrap gap-2"><Button disabled={locked} onClick={() => void checkExample()}>{zh ? "校验示例" : "Validate example"}</Button>
          <Button disabled={locked || example === "{}"} onClick={() => { setExample("{}"); setExampleAttempted(false); setPreview(null); changed() }}>{zh ? "清空示例" : "Clear example"}</Button></div>
        {preview && <Alert type={preview.allowed ? "success" : "warning"} showIcon
          title={preview.allowed ? zh ? "示例通过校验；工具未执行。" : "Example passed validation; no tool was invoked." : zh ? "示例被规则拒绝；工具未执行。" : "Example rejected by a rule; no tool was invoked."}
          description={preview.rule_id ? (zh ? "规则 " : "Rule ") + preview.rule_id + " · " + (preview.pointer || (zh ? "整个参数对象" : "Argument object")) : undefined} />}
      </div>
    </details>
    {status && <p role="status" className="text-sm">{status}</p>}
  </FormDialog>{confirmDialog}</>
}
