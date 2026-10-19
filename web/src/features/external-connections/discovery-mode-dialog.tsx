import { useCallback, useEffect, useRef, useState, type ComponentProps } from "react"
import { Button, Input, Radio, Switch } from "antd"
import { FormDialog } from "@/components/form-dialog"
import { FieldLabel } from "@/components/field-help"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import type { Locale, TFunction } from "@/i18n"
import type { ToolDiscoveryMode } from "@/features/mcp-client-settings"
import { OAuthRequestError, oauthRequest } from "./oauth-api"
import type { AuthorizationRow } from "./my-authorizations-model"
import { DEFAULT_BUDGET, PinPicker, type Budget, type Pin } from "./discovery-preferences"

type Setting = { tool_discovery_mode: ToolDiscoveryMode; discovery_revision: number; csrf: string; pinned_tools: Pin[]; result_budget: Budget }
type BudgetDraft = Omit<Budget, "max_characters"> & { max_characters: string }
const toBudgetDraft = (value: Budget): BudgetDraft => ({ ...value, max_characters: String(value.max_characters) })
const validPreviewLength = (value: string) => /^\d+$/.test(value) && Number(value) >= 1024 && Number(value) <= 65536

export function discoveryLabel(mode: ToolDiscoveryMode, zh: boolean) {
  return mode === "direct" ? zh ? "完整工具列表" : "Full tool list" : zh ? "按需发现" : "On demand"
}

export function DiscoveryModeDialog({ target, locale, t, onClose, onSaved, onCloseAutoFocus }: {
  target: AuthorizationRow | null; locale: Locale; t: TFunction; onClose: () => void; onSaved: () => void
  onCloseAutoFocus?: ComponentProps<typeof FormDialog>["onCloseAutoFocus"]
}) {
  const zh = locale === "zh-CN"
  const [saved, setSaved] = useState<Setting | null>(null), [mode, setMode] = useState<ToolDiscoveryMode>("on_demand")
  const [pins, setPins] = useState<Pin[]>([]), [budgetDraft, setBudgetDraft] = useState<BudgetDraft>(() => toBudgetDraft(DEFAULT_BUDGET))
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [refreshRequired, setRefreshRequired] = useState(false)
  const generation = useRef(0)
  const lastValidLength = useRef(String(DEFAULT_BUDGET.max_characters))
  const language = useRef(zh)
  language.current = zh
  const { confirm, confirmDialog } = useConfirm(t, true)
  const path = target ? `/v1/auth/authorizations/${target.kind}/${encodeURIComponent(target.id)}/discovery` : ""
  const budget = { ...budgetDraft, max_characters: Number(budgetDraft.max_characters) }
  const budgetValid = validPreviewLength(budgetDraft.max_characters)
  const dirty = Boolean(saved && (!budgetValid || saved.tool_discovery_mode !== mode || JSON.stringify(saved.pinned_tools) !== JSON.stringify(pins) || JSON.stringify(saved.result_budget) !== JSON.stringify(budget)))
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose })
  const load = useCallback(async (preserve = false) => {
    if (!path) return
    const current = ++generation.current
    setBusy(true); setError(null)
    try {
      const next = await oauthRequest<Setting>(path)
      if (generation.current !== current) return
      next.pinned_tools ??= []; next.result_budget ??= DEFAULT_BUDGET
      setSaved(next); if (!preserve) { setMode(next.tool_discovery_mode); setPins(next.pinned_tools); setBudgetDraft(toBudgetDraft(next.result_budget)); lastValidLength.current = String(next.result_budget.max_characters) }
      setRefreshRequired(false)
    } catch {
      if (generation.current === current) { setError(language.current ? "读取失败，请重试。" : "Unable to load. Retry."); setRefreshRequired(true) }
    } finally { if (generation.current === current) setBusy(false) }
  }, [path])
  useEffect(() => {
    setSaved(null); setMode("on_demand"); setPins([]); setBudgetDraft(toBudgetDraft(DEFAULT_BUDGET)); lastValidLength.current = String(DEFAULT_BUDGET.max_characters); setRefreshRequired(false); setError(null)
    void load()
    return () => { generation.current++ }
  }, [load])

  async function save(trigger: HTMLElement) {
    if (!saved || !target || busy || refreshRequired || !budgetValid) return
    const current = generation.current
    const body = { tool_discovery_mode: mode, expected_revision: saved.discovery_revision, csrf: saved.csrf, pinned_tools: pins, result_budget: budget }
    setBusy(true); setError(null)
    let writing = false
    try {
      const preview = await oauthRequest<{ csrf: string; previous: ToolDiscoveryMode; tool_discovery_mode: ToolDiscoveryMode }>(`${path}-preview`, body)
      if (generation.current !== current) return
      if (!(await confirm({ title: zh ? "确认调整工具发现与结果？" : "Confirm discovery and result settings?", description: `${target.name} · ${discoveryLabel(preview.previous, zh)} → ${discoveryLabel(preview.tool_discovery_mode, zh)} · ${pins.length} ${zh ? "个固定工具" : "pins"} · ${budget.enabled ? `${budget.max_characters} ${zh ? "字符预览" : "character preview"}` : zh ? "完整结果" : "Full results"}`, returnFocus: trigger }))) {
        await load(true); return
      }
      if (generation.current !== current) return
      writing = true
      await oauthRequest(path, { ...body, csrf: preview.csrf })
      if (generation.current !== current) return
      onSaved(); onClose()
    } catch (cause) {
      if (generation.current !== current) return
      const unknown = writing && (!(cause instanceof OAuthRequestError) || cause.status === 0)
      setError(unknown ? zh ? "保存结果未知，请刷新核对后再操作。" : "Save outcome unknown. Refresh before another write."
        : zh ? "设置或会话已变化，请刷新核对后重试。" : "Settings or session changed. Refresh before retrying.")
      setRefreshRequired(true)
    } finally { if (generation.current === current) setBusy(false) }
  }

  return <><FormDialog open={Boolean(target)} title={zh ? "工具发现与结果" : "Tool discovery and results"} closeLabel={t("close")} onClose={() => void close()} pending={busy} dirty={dirty} error={error}
    className="sm:max-w-[800px]" bodyClassName="space-y-5" onCloseAutoFocus={onCloseAutoFocus}
    onEscapeKeyDown={event => { if (event.target instanceof Element && event.target.closest('[role="combobox"][aria-expanded="true"]')) event.preventDefault() }}
    footer={<><Button disabled={busy} onClick={() => void close()}>{t("cancel")}</Button><Button disabled={busy} onClick={() => void load(dirty)}>{zh ? "刷新" : "Refresh"}</Button><Button type="primary" disabled={busy || !dirty || refreshRequired || !budgetValid} onClick={event => void save(event.currentTarget)}>{t("save")}</Button></>}>
    <p className="mb-4 text-sm text-muted-foreground">{target?.name}</p>
    <div className="authorization-field"><label id="authorization-discovery-label">{zh ? "工具发现" : "Tool discovery"}</label>
      <Radio.Group aria-labelledby="authorization-discovery-label" value={saved ? mode : undefined} disabled={busy || !saved || refreshRequired} onChange={event => setMode(event.target.value)}>
        <Radio value="on_demand">{discoveryLabel("on_demand", zh)}</Radio><Radio value="direct">{discoveryLabel("direct", zh)}</Radio>
      </Radio.Group>
    </div>
    <div className="authorization-field !items-start"><label>{zh ? "固定工具" : "Pinned tools"}</label>
      <PinPicker key={path} pins={pins} onChange={setPins} zh={zh} disabled={busy || !saved || refreshRequired} />
    </div>
    <div className="authorization-field"><label htmlFor="result-budget-enabled">{zh ? "长文本预览" : "Long text preview"}</label>
      <Switch id="result-budget-enabled" className="justify-self-start" checked={budget.enabled} disabled={busy || !saved || refreshRequired}
        onChange={enabled => setBudgetDraft(previous => ({ ...previous, enabled, max_characters: !enabled && !validPreviewLength(previous.max_characters) ? lastValidLength.current : previous.max_characters }))} />
    </div>
    {budget.enabled && <div className="authorization-field !items-start"><label htmlFor="result-budget-characters"><FieldLabel label={zh ? "预览长度" : "Preview length"} help={zh ? "1024～65536 个 Unicode 字符。仅成功的单段纯文本适用，原文保留五分钟，可分段取回。" : "1,024–65,536 Unicode characters. Applies to successful single plain-text results. Originals remain available for five minutes."} helpId="result-budget-help" zh={zh} /></label><div>
      <Input id="result-budget-characters" aria-label={zh ? "预览长度" : "Preview length"} type="number" inputMode="numeric" min={1024} max={65536} step={1} className="max-w-[240px]" value={budgetDraft.max_characters} status={budgetValid ? undefined : "error"}
        aria-invalid={!budgetValid} aria-describedby={budgetValid ? "result-budget-help result-budget-effect" : "result-budget-error result-budget-help result-budget-effect"}
        disabled={busy || !saved || refreshRequired} onChange={event => {
          const value = event.target.value
          if (validPreviewLength(value)) lastValidLength.current = value
          setBudgetDraft(previous => ({ ...previous, max_characters: value }))
        }} />
      {!budgetValid && <p id="result-budget-error" role="alert" className="mt-2 text-sm text-destructive">{zh ? "请输入 1024～65536 的整数，或关闭长文本预览。" : "Enter an integer from 1,024 to 65,536, or turn off long text preview."}</p>}
      <p id="result-budget-effect" className="mt-2 text-xs text-muted-foreground">{zh ? "设置变化会使已有结果引用失效。" : "Changing these settings invalidates saved references."}</p>
    </div></div>}
  </FormDialog>{confirmDialog}</>
}
