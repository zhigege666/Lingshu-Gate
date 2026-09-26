import { useEffect, useMemo, useRef, useState } from "react"
import { App as AntApp, Alert, Button, Empty, Input, Segmented, Select, Spin, Tag } from "antd"
import { Braces, ChevronDown, ChevronRight, Copy, FileInput, Info, Play, RotateCcw, Server, Terminal } from "lucide-react"
import { api, type McpServer, type ToolDefinition } from "@/api/client"
import { PageHeader } from "@/components/page-shell"
import { JsonPanel } from "@/components/json-panel"
import { ArgumentForm, ArgumentReference } from "@/features/invoke/argument-form"
import { invokeCopy } from "@/features/invoke/copy"
import { createInvokeDraft, draftKey, responseSucceeded, serviceOptions, toolServiceKey, updateDraft, type InvokeDraft } from "@/features/invoke/model"
import { changeArgument, createArgumentExample, parseArguments, schemaFields, validateArguments } from "@/features/invoke/schema"
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
}

export function InvokePage({locale,t,tools,servers,toolsLoaded,toolsError,selectedToolId,onToolChange,onRefresh}:InvokePageProps) {
  const c=invokeCopy(locale)
  const {message}=AntApp.useApp()
  const selectedTool=tools.find(tool=>tool.id === selectedToolId)
  const groups=useMemo(()=>serviceOptions(tools,servers,c),[tools,servers,locale])
  const [emptyService,setEmptyService]=useState<string|null>(null)
  const selectedService=selectedTool ? toolServiceKey(selectedTool) : emptyService || groups[0]?.key || ""
  const service=groups.find(item=>item.key === selectedService)
  const [drafts,setDrafts]=useState<Record<string,InvokeDraft>>({})
  const [lastTool,setLastTool]=useState<Record<string,string>>({})
  const [docsOpen,setDocsOpen]=useState(true)
  const [schemaOpen,setSchemaOpen]=useState(false)
  const [undo,setUndo]=useState<{key:string;draft:InvokeDraft}|null>(null)
  const running=useRef(new Set<string>())
  const mounted=useRef(true)
  const key=selectedTool ? draftKey(selectedTool) : ""
  const initial=useMemo(()=>selectedTool ? createInvokeDraft(selectedTool) : null,[selectedTool])
  const draft=key && initial ? drafts[key] || initial : null
  const parsed=useMemo(()=>parseArguments(draft?.text || "{}"),[draft?.text])
  const schemaChanged=selectedTool && draft && draft.schemaVersion !== JSON.stringify(selectedTool.input_schema)
  const editError=draft?.error || (!parsed.ok ? c[parsed.error] : null)

  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false}},[])
  // Capture initial samples once; catalog refreshes must not overwrite a draft.
  useEffect(()=>{
    if (!key || !initial) return
    setDrafts(previous=>previous[key] ? previous : {...previous,[key]:initial})
  },[key,initial])

  function patch(changes:Partial<InvokeDraft>) {
    if (initial) setDrafts(previous=>updateDraft(previous,key,initial,changes))
  }
  function selectTool(id:string) {
    const next=tools.find(tool=>tool.id === id)
    if (next) setLastTool(previous=>({...previous,[toolServiceKey(next)]:next.id}))
    setSchemaOpen(false);setUndo(null);onToolChange(id)
  }
  function selectService(nextKey:string) {
    const next=groups.find(group=>group.key === nextKey)
    if (!next) return
    if (selectedTool) setLastTool(previous=>({...previous,[selectedService]:selectedTool.id}))
    setEmptyService(nextKey)
    selectTool(next.tools.find(tool=>tool.id === lastTool[nextKey])?.id || next.tools[0]?.id || "")
  }
  function switchMode(mode:"form"|"json") {
    if (!selectedTool || !draft) return
    if (mode === "form" && !parsed.ok) {patch({error:c[parsed.error]});return}
    if (mode === "form" && !schemaFields(selectedTool.input_schema)) {patch({error:c.unsupported});return}
    patch({mode,error:null})
  }
  function replaceArguments(mode:"example"|"defaults") {
    if (!selectedTool || !draft || draft.pending) return
    setUndo({key,draft})
    patch({...createArgumentExample(selectedTool.input_schema,mode),source:mode,error:null,schemaVersion:JSON.stringify(selectedTool.input_schema)})
  }
  function changeField(path:string[],value:unknown) {
    if (!draft) return
    const text=changeArgument(draft.text,path,value)
    if (text !== null) patch({text,source:"edited",error:null})
  }
  function format() {
    if (parsed.ok) patch({text:JSON.stringify(parsed.value,null,2),error:null})
    else patch({error:c[parsed.error]})
  }
  async function run() {
    if (!selectedTool || !draft || !initial || !toolsLoaded || toolsError || running.current.has(key)) return
    const validation=validateArguments(selectedTool.input_schema,draft.text,c)
    if (!validation.ok) {patch({error:validation.error});return}
    // Freeze the service/tool identity and update only its draft when the request settles.
    const requestKey=key, requestDraft=draft, toolId=selectedTool.id, target=service?.label || selectedService
    running.current.add(requestKey)
    patch({pending:true,error:null})
    try {
      const response=await api.invoke(toolId,validation.value)
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
    <PageHeader title={c.title} description={c.description} helpLabel={t("pageHelp")} toolbar={<p className="invoke-intro">{c.description}</p>}/>
    {toolsError && <Alert type="error" showIcon title={c.loadFailed} description={toolsError} action={<Button size="small" onClick={onRefresh}>{c.retry}</Button>}/>}
    {!toolsLoaded && !toolsError ? <div className="invoke-loading"><Spin/><span>{c.loading}</span></div> : <>
      {unavailable && <Alert type="warning" showIcon title={c.unavailable}/>}
      {!groups.length ? <Empty description={<><strong>{c.empty}</strong><p>{c.emptyHint}</p></>}/> : <>
        <section className="invoke-configuration" aria-label={c.configure}>
          <div className="invoke-target">
            <h2 className="invoke-step"><span>1</span>{c.selectTarget}</h2>
            <label className="invoke-selection-label" htmlFor="invoke-service">{c.service}</label>
            <Select id="invoke-service" showSearch optionFilterProp="label" aria-label={c.service} className="invoke-selector" value={selectedService || undefined} onChange={selectService} placeholder={c.searchServices} prefix={<Server size={17}/>} options={groups.map(group=>({value:group.key,label:group.label}))}/>
            <p className="invoke-service-id">{c.serviceId}: <code>{service?.id || "—"}</code></p>
            <label className="invoke-selection-label invoke-tool-label" htmlFor="invoke-tool">{c.tool}</label>
            <Select id="invoke-tool" showSearch optionFilterProp="label" aria-label={c.tool} className="invoke-selector" value={selectedTool?.id} onChange={selectTool} placeholder={c.searchTools} notFoundContent={c.noTools} options={(service?.tools || []).map(tool=>({value:tool.id,label:tool.name && tool.name !== tool.id ? `${tool.name} · ${tool.id}` : tool.id}))}/>
            <p className="invoke-service-id">{service?.tools.length || 0} {c.available}</p>
            {selectedTool ? <><code className="invoke-tool-id">{selectedTool.id}</code><div className="invoke-tags"><Tag>{selectedTool.source}</Tag><Tag>{selectedTool.permission}</Tag></div><p className="invoke-tool-description">{selectedTool.description}</p></> : <p className="invoke-tool-description">{c.noTools}</p>}
          </div>
          <div className="invoke-parameters">
            <h2 className="invoke-step"><span>2</span>{c.configure}</h2>
            {selectedTool && draft ? <>
              <div className="invoke-editor-toolbar"><Segmented aria-label={c.editorMode} value={draft.mode} onChange={value=>switchMode(value as "form"|"json")} options={[{value:"form",label:c.form},{value:"json",label:c.json}]}/><div className="invoke-editor-actions"><Button type="link" icon={<FileInput size={16}/>} disabled={runningHere} onClick={()=>replaceArguments("example")}>{c.example}</Button><Button type="link" icon={<RotateCcw size={16}/>} disabled={runningHere} onClick={()=>replaceArguments("defaults")}>{c.defaults}</Button></div></div>
              {schemaChanged && <Alert type="warning" showIcon title={c.schemaChanged}/>}
              {draft.mode === "form" && parsed.ok ? <ArgumentForm schema={selectedTool.input_schema} value={parsed.value} disabled={runningHere} c={c} onChange={changeField} onJSON={()=>switchMode("json")}/> : <>
                <div className="invoke-json-toolbar"><label htmlFor="invoke-arguments">{c.json}</label><div><Button type="link" size="small" icon={<Braces size={15}/>} disabled={runningHere} onClick={format}>{c.format}</Button><Button type="link" size="small" aria-expanded={docsOpen} onClick={()=>setDocsOpen(!docsOpen)}>{docsOpen ? c.hideDocs : c.docs}</Button></div></div>
                <div className={`invoke-json-layout ${docsOpen ? "invoke-with-reference" : ""}`}><Input.TextArea id="invoke-arguments" aria-label={t("arguments")} aria-invalid={Boolean(editError)} aria-describedby={editError ? "invoke-arguments-error" : undefined} spellCheck={false} autoComplete="off" value={draft.text} disabled={runningHere} onChange={event=>patch({text:event.target.value,source:"edited",error:null})} onKeyDown={event=>{if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {event.preventDefault();void run()}}}/>{docsOpen && <ArgumentReference schema={selectedTool.input_schema} c={c}/>}</div>
              </>}
              {editError && <Alert className="invoke-validation" type="error" showIcon role="alert" title={<span id="invoke-arguments-error">{editError}</span>}/>}
              <Button className="invoke-schema-toggle" block type="text" aria-expanded={schemaOpen} onClick={()=>setSchemaOpen(!schemaOpen)} icon={schemaOpen ? <ChevronDown size={15}/> : <ChevronRight size={15}/>}>{t("inputSchema")}</Button>
              {schemaOpen && <JsonPanel data={selectedTool.input_schema} maxHeight="max-h-64"/>}
              <div className="invoke-source-hint"><Info size={15}/><span>{hint}</span>{undo?.key === key && <Button type="link" size="small" disabled={runningHere} onClick={()=>{patch(undo.draft);setUndo(null)}}>{c.undo}</Button>}</div>
            </> : <div className="invoke-blank">{c.noTools}</div>}
          </div>
        </section>
        <div className="invoke-run-bar"><p><Info size={16}/><span>{c.target}: {service?.label || "—"}</span></p><Button type="primary" icon={<Play size={17}/>} loading={runningHere} disabled={!selectedTool || !toolsLoaded || Boolean(toolsError) || !parsed.ok} onClick={()=>void run()}>{runningHere ? c.running : c.run}</Button></div>
        <section className="invoke-result" aria-label={c.result}>
          <div className="invoke-result-heading"><div><h2>{c.result}</h2><Tag color={runningHere ? "processing" : draft?.result ? draft.result.ok ? "success" : "error" : "default"}>{runningHere ? c.running : draft?.result ? draft.result.ok ? c.success : c.failed : c.idle}</Tag></div><Button type="text" icon={<Copy size={18}/>} aria-label={c.copy} title={c.copy} disabled={!draft?.result} onClick={()=>void copyResult()}/></div>
          <div className="invoke-result-body" aria-live="polite">{runningHere ? <div className="invoke-result-empty"><Spin/><p>{c.runningHint}</p></div> : draft?.result ? <><div className="invoke-result-target">{c.lastResult}: {draft.result.target} · <code>{draft.result.toolId}</code></div><pre>{draft.result.text}</pre></> : <div className="invoke-result-empty"><Terminal size={45} strokeWidth={1.2}/><h3>{c.waiting}</h3><p>{c.waitingHint}</p></div>}</div>
        </section>
      </>}
    </>}
  </div>
}
