import { useEffect, useMemo, useRef, useState } from "react"
import { App as AntApp, Alert, Button, Empty, Input, Segmented, Select, Spin, Tag } from "antd"
import { Braces, ChevronDown, ChevronRight, Copy, FileInput, Info, Play, RotateCcw, Server } from "lucide-react"
import { api, type McpServer, type ToolDefinition } from "@/api/client"
import { PageHeader } from "@/components/page-shell"
import { JsonPanel } from "@/components/json-panel"
import { ValidationErrors } from "@/components/validation-errors"
import { pathFor, pointerFor, type ValidationIssue } from "@/lib/validation"
import { ArgumentForm, ArgumentReference, argumentFieldId } from "@/features/invoke/argument-form"
import { invokeCopy } from "@/features/invoke/copy"
import { argumentChangeHidesPendingEntry, createInvokeDraft, draftKey, hasPendingArgumentEntries, invokeDraftIsDirty, prepareInvokeArguments, responseSucceeded, serviceOptions, snapshotArguments, toolServiceKey, updateDraft, type ArgumentSnapshot, type InvokeDraft } from "@/features/invoke/model"
import { changeArgument, createArgumentExample, parseArguments, schemaFields } from "@/features/invoke/schema"
import { getToolAccessDisplay } from "@/features/tool-access"
import type { Locale, TFunction } from "@/i18n"
import "./invoke-page.css"

type InvokePageProps = {
  locale:Locale
  t:TFunction
  tools:ToolDefinition[]
  servers:McpServer[]
  toolsLoaded:boolean
  toolsError:string|null
  selectedToolId:string
  onToolChange:(value:string)=>void
  onRefresh:()=>void
  onLeaveStateChange?:(state:{dirty:boolean;pending:boolean})=>void
}

export function InvokePage({locale,t,tools,servers,toolsLoaded,toolsError,selectedToolId,onToolChange,onRefresh,onLeaveStateChange}:InvokePageProps) {
  const c=invokeCopy(locale)
  const {message}=AntApp.useApp()
  const selectedTool=tools.find(tool=>tool.id === selectedToolId)
  const groups=useMemo(()=>serviceOptions(tools,servers,c),[tools,servers,locale])
  const [emptyService,setEmptyService]=useState<string|null>(null)
  const selectedService=selectedTool ? toolServiceKey(selectedTool) : emptyService || groups[0]?.key || ""
  const service=groups.find(item=>item.key === selectedService)
  const [drafts,setDrafts]=useState<Record<string,InvokeDraft>>({})
  const [lastTool,setLastTool]=useState<Record<string,string>>({})
  const [docsOpen,setDocsOpen]=useState(false)
  const [schemaOpen,setSchemaOpen]=useState(false)
  const [undo,setUndo]=useState<{key:string;snapshot:ArgumentSnapshot}|null>(null)
  const running=useRef(new Set<string>())
  const mounted=useRef(true)
  const key=selectedTool ? draftKey(selectedTool) : ""
  const initial=useMemo(()=>selectedTool ? createInvokeDraft(selectedTool) : null,[selectedTool])
  const draft=key && initial ? drafts[key] || initial : null
  const parsed=useMemo(()=>parseArguments(draft?.text || "{}"),[draft?.text])
  const schemaChanged=selectedTool && draft && draft.schemaVersion !== JSON.stringify(selectedTool.input_schema)
  const validation=useMemo(()=>selectedTool && draft && (draft.validationAttempted || !parsed.ok) ? prepareInvokeArguments(selectedTool,draft,c) : null,[selectedTool,draft?.text,draft?.pendingEntries,draft?.validationAttempted,draft?.revision,locale,parsed.ok])
  const issues=validation && !validation.ok ? validation.issues : []
  const access=selectedTool ? getToolAccessDisplay(selectedTool) : null
  const accessLabel=access?.pending ? c.accessPending : access?.access === "read" ? c.accessRead : access?.access === "write" ? c.accessWrite : c.accessUnknown
  const dirty=Object.values(drafts).some(invokeDraftIsDirty)
  const pending=Object.values(drafts).some(item=>item.pending)

  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false}},[])
  useEffect(()=>{onLeaveStateChange?.({dirty,pending})},[dirty,pending,onLeaveStateChange])
  useEffect(()=>()=>onLeaveStateChange?.({dirty:false,pending:false}),[onLeaveStateChange])
  // Capture samples once; catalog refreshes must not overwrite an edited draft.
  useEffect(()=>{
    if (!key || !initial) return
    setDrafts(previous=>previous[key] ? previous : {...previous,[key]:initial})
  },[key,initial])

  function patch(changes:Partial<InvokeDraft>) {
    if (initial) setDrafts(previous=>updateDraft(previous,key,initial,changes))
  }
  function revealPendingEntry(pointer:string) {
    const input=document.getElementById(argumentFieldId(pathFor(pointer)))
    if (!input) patch({error:c.pendingEntryUnavailable})
    const field=input || document.getElementById("invoke-pending-entries")
    field?.focus();field?.scrollIntoView({block:"center",behavior:"smooth"})
  }
  function blockPendingEntries() {
    if (!draft || !hasPendingArgumentEntries(draft)) return false
    patch({error:c.pendingEntryHint})
    revealPendingEntry(Object.keys(draft.pendingEntries)[0])
    return true
  }
  function changePendingEntry(path:string[],value:string) {
    if (!draft || draft.pending) return
    const pendingEntries={...draft.pendingEntries}
    if (value.length) pendingEntries[pointerFor(path)]=value
    else delete pendingEntries[pointerFor(path)]
    patch({pendingEntries,error:null})
  }
  function selectTool(id:string) {
    if (id === selectedToolId) return
    if (blockPendingEntries()) return
    const next=tools.find(tool=>tool.id === id)
    if (next) setLastTool(previous=>({...previous,[toolServiceKey(next)]:next.id}))
    setSchemaOpen(false);setUndo(null);onToolChange(id)
  }
  function selectService(nextKey:string) {
    if (nextKey === selectedService) return
    if (blockPendingEntries()) return
    const next=groups.find(group=>group.key === nextKey)
    if (!next) return
    if (selectedTool) setLastTool(previous=>({...previous,[selectedService]:selectedTool.id}))
    setEmptyService(nextKey)
    selectTool(next.tools.find(tool=>tool.id === lastTool[nextKey])?.id || next.tools[0]?.id || "")
  }
  function switchMode(mode:"form"|"json") {
    if (!selectedTool || !draft) return
    if (mode !== draft.mode && blockPendingEntries()) return
    if (mode === "form" && !parsed.ok) {patch({validationAttempted:true});return}
    if (mode === "form" && !schemaFields(selectedTool.input_schema)) {patch({error:c.unsupported});return}
    patch({mode,error:null})
  }
  function replaceArguments(mode:"example"|"defaults") {
    if (!selectedTool || !draft || draft.pending) return
    if (blockPendingEntries()) return
    setUndo({key,snapshot:snapshotArguments(draft)})
    patch({...createArgumentExample(selectedTool.input_schema,mode),source:mode,error:null,schemaVersion:JSON.stringify(selectedTool.input_schema)})
  }
  function changeField(path:string[],value:unknown) {
    if (!draft || draft.pending) return false
    if (argumentChangeHidesPendingEntry(draft.pendingEntries,path)) {blockPendingEntries();return false}
    const text=changeArgument(draft.text,path,value)
    if (text === null) return false
    patch({text,source:"edited",error:null})
    return true
  }
  function format() {
    if (blockPendingEntries()) return
    if (parsed.ok) patch({text:JSON.stringify(parsed.value,null,2),error:null})
    else patch({validationAttempted:true})
  }
  function focusIssue(issue:ValidationIssue) {
    const field=draft?.mode === "form" ? document.getElementById(argumentFieldId(pathFor(issue.path))) : null
    if (field) {field.focus();field.scrollIntoView({block:"center",behavior:"smooth"});return}
    if (blockPendingEntries()) return
    patch({mode:"json",error:null})
    requestAnimationFrame(()=>{
      const editor=document.getElementById("invoke-arguments") as HTMLTextAreaElement|null
      editor?.focus();editor?.scrollIntoView({block:"center",behavior:"smooth"})
      if (issue.range) editor?.setSelectionRange(issue.range.start,issue.range.end)
    })
  }
  async function run() {
    if (!selectedTool || !draft || !initial || !toolsLoaded || toolsError || running.current.has(key)) return
    const checked=prepareInvokeArguments(selectedTool,draft,c)
    if (!checked.ok) {patch({validationAttempted:true,error:null});requestAnimationFrame(()=>focusIssue(checked.issues[0]));return}
    // Freeze service/tool identity and update only its draft when the request settles.
    const requestKey=key, requestDraft=draft, toolId=selectedTool.id, target=service?.label || selectedService
    running.current.add(requestKey)
    patch({pending:true,error:null,validationAttempted:true})
    try {
      const response=await api.invoke(toolId,checked.value)
      if (mounted.current) setDrafts(previous=>updateDraft(previous,requestKey,requestDraft,{pending:false,result:{text:JSON.stringify(response,null,2),ok:responseSucceeded(response),toolId,target}}))
    } catch (error) {
      if (mounted.current) setDrafts(previous=>updateDraft(previous,requestKey,requestDraft,{pending:false,result:{text:error instanceof Error ? error.message : String(error),ok:false,toolId,target}}))
    } finally {running.current.delete(requestKey)}
  }
  async function copyResult() {
    if (!draft?.result) return
    try {await navigator.clipboard.writeText(draft.result.text);message.success(c.copied)} catch {message.error(c.copyFailed)}
  }
  const hint=draft?.source === "edited" ? c.editedHint : draft?.source === "defaults" ? c.defaultsHint : draft?.declared ? c.sampleHint : c.noSampleHint
  const unavailable=Boolean(selectedToolId && !selectedTool)
  const runningHere=Boolean(draft?.pending)
  return <div className="invoke-workspace">
    <PageHeader title={c.title} description={c.description} helpLabel={t("pageHelp")} toolbar={(toolsLoaded || toolsError) && groups.length > 0 ? <section className="invoke-target" aria-label={c.selectTarget}>
          <div className="invoke-target-selectors">
            <div><label className="invoke-selection-label" htmlFor="invoke-service">{c.service}</label><Select id="invoke-service" showSearch optionFilterProp="label" aria-label={c.service} className="invoke-selector" value={selectedService || undefined} onChange={selectService} placeholder={c.searchServices} prefix={<Server size={16}/>} options={groups.map(group=>({value:group.key,label:group.label}))}/></div>
            <div><label className="invoke-selection-label" htmlFor="invoke-tool">{c.tool}</label><Select id="invoke-tool" showSearch optionFilterProp="label" aria-label={c.tool} className="invoke-selector" value={selectedTool?.id} onChange={selectTool} placeholder={c.searchTools} notFoundContent={c.noTools} options={(service?.tools || []).map(tool=>({value:tool.id,label:tool.name && tool.name !== tool.id ? `${tool.name} · ${tool.id}` : tool.id}))}/></div>
          </div>
          {selectedTool && <details className="invoke-tool-details"><summary>{c.toolDetails} <Tag color={access?.access === "write" ? "orange" : undefined}>{accessLabel}</Tag></summary><dl><dt>{c.serviceId}</dt><dd><code>{service?.id || "—"}</code></dd><dt>{c.tool}</dt><dd><code>{selectedTool.id}</code></dd></dl>{selectedTool.description && <p className="invoke-tool-description">{selectedTool.description}</p>}</details>}
        </section> : undefined}/>
    {toolsError && <Alert type="error" showIcon title={c.loadFailed} description={toolsError} action={<Button size="small" onClick={onRefresh}>{c.retry}</Button>}/>}
    {!toolsLoaded && !toolsError ? <div className="invoke-loading"><Spin/><span>{c.loading}</span></div> : <>
      {unavailable && <Alert type="warning" showIcon title={c.unavailable}/>}
      {!groups.length ? <Empty description={<><strong>{c.empty}</strong><p>{c.emptyHint}</p></>}/> : <>
        <section className="invoke-parameters" aria-label={c.configure}>
          {selectedTool && draft ? <>
            <div className="invoke-editor-toolbar"><Segmented aria-label={c.editorMode} value={draft.mode} disabled={runningHere} onChange={value=>switchMode(value as "form"|"json")} options={[{value:"form",label:c.form},{value:"json",label:c.json}]}/><div className="invoke-editor-actions"><Button type="link" icon={<FileInput size={16}/>} disabled={runningHere} onClick={()=>replaceArguments("example")}>{c.example}</Button><Button type="link" icon={<RotateCcw size={16}/>} disabled={runningHere} onClick={()=>replaceArguments("defaults")}>{c.defaults}</Button>{undo?.key === key && <Button type="link" disabled={runningHere} onClick={()=>{if (blockPendingEntries()) return;patch({...undo.snapshot,error:null});setUndo(null)}}>{c.undo}</Button>}</div></div>
            {schemaChanged && <Alert type="warning" showIcon title={c.schemaChanged}/>}
            {hasPendingArgumentEntries(draft) && <div id="invoke-pending-entries" tabIndex={-1} className="invoke-pending-notice"><Alert type="warning" showIcon title={c.pendingEntryHint} description={<ul className="invoke-pending-list">{Object.entries(draft.pendingEntries).map(([pointer,value])=><li key={pointer}><span><code>{pointer || c.json}</code>: {value}</span><div><Button type="link" size="small" disabled={runningHere} onClick={()=>revealPendingEntry(pointer)}>{c.locatePendingEntry}</Button><Button type="link" size="small" disabled={runningHere} onClick={()=>changePendingEntry(pathFor(pointer),"")}>{c.clearPendingEntry}</Button></div></li>)}</ul>}/></div>}
            <ValidationErrors id="invoke-validation-summary" issues={issues} title={c.validationTitle} onSelect={focusIssue}/>
            {draft.error && <Alert type="error" showIcon role="alert" title={draft.error}/>}
            {draft.mode === "form" && parsed.ok ? <ArgumentForm key={key} schema={selectedTool.input_schema} value={parsed.value} disabled={runningHere} c={c} issues={issues} pendingEntries={draft.pendingEntries} onPendingEntryChange={changePendingEntry} onChange={changeField} onJSON={()=>switchMode("json")}/> : <>
              <div className="invoke-json-toolbar"><label htmlFor="invoke-arguments">{c.json}</label><div><Button type="link" size="small" icon={<Braces size={15}/>} disabled={runningHere} onClick={format}>{c.format}</Button><Button type="link" size="small" aria-expanded={docsOpen} onClick={()=>setDocsOpen(!docsOpen)}>{docsOpen ? c.hideDocs : c.docs}</Button></div></div>
              <div className={`invoke-json-layout ${docsOpen ? "invoke-with-reference" : ""}`}><Input.TextArea id="invoke-arguments" aria-label={t("arguments")} aria-invalid={Boolean(issues.length)} aria-describedby={issues.length ? "invoke-validation-summary" : undefined} spellCheck={false} autoComplete="off" value={draft.text} disabled={runningHere} onChange={event=>patch({text:event.target.value,source:"edited",error:null})} onKeyDown={event=>{if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {event.preventDefault();void run()}}}/>{docsOpen && <ArgumentReference schema={selectedTool.input_schema} c={c}/>}</div>
            </>}
            <div className="invoke-editor-footer"><p className="invoke-source-hint"><Info size={14}/><span>{hint}</span></p><Button type="text" aria-expanded={schemaOpen} onClick={()=>setSchemaOpen(!schemaOpen)} icon={schemaOpen ? <ChevronDown size={15}/> : <ChevronRight size={15}/>}>{t("inputSchema")}</Button></div>
            {schemaOpen && <JsonPanel data={selectedTool.input_schema} maxHeight="max-h-64"/>}
          </> : <div className="invoke-blank">{c.noTools}</div>}
        </section>
        <div className="invoke-run-bar"><p><span>{c.target}: <code>{selectedTool?.id || service?.label || "—"}</code></span></p><Button type="primary" icon={<Play size={17}/>} loading={runningHere} disabled={!selectedTool || !toolsLoaded || Boolean(toolsError) || !parsed.ok} onClick={()=>void run()}>{runningHere ? c.running : c.run}</Button></div>
        <section className="invoke-result" aria-label={c.result}>
          <div className="invoke-result-heading"><div><h2>{c.result}</h2><Tag color={runningHere ? "processing" : draft?.result ? draft.result.ok ? "success" : "error" : "default"}>{runningHere ? c.running : draft?.result ? draft.result.ok ? c.success : c.failed : c.idle}</Tag></div>{draft?.result && <Button type="text" icon={<Copy size={18}/>} aria-label={c.copy} title={c.copy} disabled={runningHere} onClick={()=>void copyResult()}/>}</div>
          <div className="invoke-result-body" aria-live="polite">{runningHere ? <div className="invoke-result-empty"><Spin size="small"/><span>{c.runningHint}</span></div> : draft?.result ? <><div className="invoke-result-target">{c.lastResult}: {draft.result.target} · <code>{draft.result.toolId}</code></div><pre>{draft.result.text}</pre></> : <p className="invoke-result-empty">{c.waitingHint}</p>}</div>
        </section>
      </>}
    </>}
  </div>
}
