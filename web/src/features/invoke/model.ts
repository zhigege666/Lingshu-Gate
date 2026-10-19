import type { McpServer, ToolDefinition } from "@/api/client"
import type { InvokeCopy } from "./copy"
import { changeArgument, createArgumentExample, parseArguments, schemaFields, validateArguments, valueAt } from "./schema"
import { pathFor, pointerFor, type ValidationIssue } from "@/lib/validation"

export function toolServiceKey(tool: ToolDefinition): string {
  const id=tool.metadata.server_id
  return tool.source === "mcp" ? typeof id === "string" && id ? JSON.stringify(["mcp",id]) : JSON.stringify(["unresolved",tool.id]) : JSON.stringify(["source",tool.source])
}
export const draftKey = (tool: ToolDefinition) => JSON.stringify([toolServiceKey(tool),tool.id])
export type ServiceOption = { key:string;label:string;id:string;tools:ToolDefinition[] }
export function serviceOptions(tools: ToolDefinition[],servers: McpServer[],c: InvokeCopy): ServiceOption[] {
  const groups=new Map<string,ServiceOption>()
  for (const server of servers) {
    const key=JSON.stringify(["mcp",server.id])
    groups.set(key,{key,label:server.name && server.name !== server.id ? `${server.name} · ${server.id}` : server.id,id:server.id,tools:[]})
  }
  for (const tool of tools) {
    const key=toolServiceKey(tool)
    if (!groups.has(key)) {
      const id=typeof tool.metadata.server_id === "string" ? tool.metadata.server_id : tool.source
      const label=tool.source === "builtin" ? c.builtin : tool.source === "mcp" && !tool.metadata.server_id ? c.unknownService : id
      groups.set(key,{key,label,id,tools:[]})
    }
    groups.get(key)!.tools.push(tool)
  }
  return [...groups.values()].sort((a,b)=>Number(!a.tools.length)-Number(!b.tools.length) || a.label.localeCompare(b.label))
}
export type InvocationResult = {text:string;ok:boolean;toolId:string;target:string}
export type PendingArgumentEntry = string | {kind:"number";raw:string}
export type PendingArgumentEntries = Record<string,PendingArgumentEntry>
export type ArgumentChangeIntent = "resolve-number"
export type InvokeDraft = {text:string;mode:"form"|"json";source:"example"|"defaults"|"edited";declared:boolean;schemaVersion:string;error:string|null;pending:boolean;result:InvocationResult|null;revision:number;validationAttempted:boolean;initialText:string;pendingEntries:PendingArgumentEntries}
export const pendingArgumentText = (entry:PendingArgumentEntry) => typeof entry === "string" ? entry : entry.raw
export const hasPendingArgumentEntries = (draft:Pick<InvokeDraft,"pendingEntries">) => Object.values(draft.pendingEntries).some(entry=>pendingArgumentText(entry).length > 0)
export const pendingArgumentHint = (entry:PendingArgumentEntry,c:InvokeCopy) => typeof entry === "string" ? c.pendingEntryHint : c.required === "必填" ? "请完成或清除未完成的数值，再运行、切换工具或编辑方式。只接受有限数字，整数须在安全精度范围内。" : "Complete or clear the unfinished number before running, switching tools or changing editor mode. Numbers must be finite and integers must stay within the safe range."
export const clearPendingArgumentLabel = (entry:PendingArgumentEntry,c:InvokeCopy) => typeof entry === "string" ? c.clearPendingEntry : c.required === "必填" ? "清除数值草稿" : "Clear numeric draft"
export const invokeDraftIsDirty = (draft:InvokeDraft) => draft.text !== draft.initialText || hasPendingArgumentEntries(draft)
/** Parent replacement/removal must not orphan unfinished names or numeric text. */
export function argumentChangeHidesPendingEntry(entries:PendingArgumentEntries,path:string[]) {
  return Object.entries(entries).some(([pointer,entry])=>pendingArgumentText(entry).length > 0 && path.length <= pathFor(pointer).length && path.every((part,index)=>part === pathFor(pointer)[index]))
}
/** Parse form text only when complete; never round unsafe integers into the draft. */
export function parseArgumentNumber(raw:string,integer:boolean):{ok:true;value:number|undefined}|{ok:false} {
  if (raw === "") return {ok:true,value:undefined}
  const number=Number(raw)
  if (!/^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw) || !Number.isFinite(number) || Number.isInteger(number) && !Number.isSafeInteger(number) || integer && !Number.isInteger(number)) return {ok:false}
  return {ok:true,value:number}
}
/** A numeric correction clears only its own draft, in the same text transaction. */
export function changeInvokeArgument(draft:InvokeDraft,path:string[],value:unknown,intent?:ArgumentChangeIntent):{ok:true;text:string;pendingEntries:PendingArgumentEntries}|{ok:false;reason:"pending-entry"|"invalid-source"|"invalid-number"} {
  if (intent === "resolve-number" && value !== undefined && (typeof value !== "number" || !Number.isFinite(value) || Number.isInteger(value) && !Number.isSafeInteger(value))) return {ok:false,reason:"invalid-number"}
  let pendingEntries=draft.pendingEntries
  const pointer=pointerFor(path),entry=pendingEntries[pointer]
  if (intent === "resolve-number" && entry && typeof entry !== "string") {
    pendingEntries={...pendingEntries}
    delete pendingEntries[pointer]
  }
  // Removing an array item renumbers siblings; keep all their drafts attached.
  let changedPath=path
  if (value === undefined && path.length > 1 && Object.keys(pendingEntries).length) {
    const parsed=parseArguments(draft.text)
    if (!parsed.ok) return {ok:false,reason:"invalid-source"}
    if (Array.isArray(valueAt(parsed.value,path.slice(0,-1)))) changedPath=path.slice(0,-1)
  }
  if (argumentChangeHidesPendingEntry(pendingEntries,changedPath)) return {ok:false,reason:"pending-entry"}
  const text=changeArgument(draft.text,path,value)
  return text === null ? {ok:false,reason:"invalid-source"} : {ok:true,text,pendingEntries}
}
/** The only preparation entry point used by Run; unadded input is never omitted. */
export function prepareInvokeArguments(tool:ToolDefinition,draft:InvokeDraft,c:InvokeCopy) {
  if (hasPendingArgumentEntries(draft)) {
    const issues:ValidationIssue[]=Object.entries(draft.pendingEntries).filter(([,entry])=>pendingArgumentText(entry).length > 0).map(([path,entry])=>({code:typeof entry === "string" ? "pendingEntry" : "pendingNumber",messageKey:typeof entry === "string" ? "pendingEntryHint" : "pendingNumberHint",message:pendingArgumentHint(entry,c),severity:"error",source:"domain",path,revision:draft.revision}))
    return {ok:false as const,error:issues[0].message,issues}
  }
  return validateArguments(tool.input_schema,draft.text,c,draft.revision)
}
export type ArgumentSnapshot = Pick<InvokeDraft,"text"|"mode"|"source"|"declared"|"schemaVersion">
export function snapshotArguments(draft:InvokeDraft):ArgumentSnapshot {
  const {text,mode,source,declared,schemaVersion}=draft
  return {text,mode,source,declared,schemaVersion}
}
export function createInvokeDraft(tool: ToolDefinition): InvokeDraft {
  const example=createArgumentExample(tool.input_schema)
  return {...example,initialText:example.text,mode:schemaFields(tool.input_schema) ? "form" : "json",source:"example",schemaVersion:JSON.stringify(tool.input_schema),error:null,pending:false,result:null,revision:0,validationAttempted:false,pendingEntries:{}}
}
export function updateDraft(drafts: Record<string,InvokeDraft>,key:string,initial:InvokeDraft,changes:Partial<InvokeDraft>) {
  const current=drafts[key] || initial
  const changed=changes.text !== undefined && changes.text !== current.text || changes.pendingEntries !== undefined && JSON.stringify(changes.pendingEntries) !== JSON.stringify(current.pendingEntries)
  const revision=changed ? current.revision+1 : current.revision
  return {...drafts,[key]:{...current,...changes,revision}}
}
export function responseSucceeded(response: unknown): boolean {
  if (!response || typeof response !== "object") return true
  const result=response as {ok?:boolean;isError?:boolean;output?:{isError?:boolean}}
  return result.ok !== false && result.isError !== true && result.output?.isError !== true
}
