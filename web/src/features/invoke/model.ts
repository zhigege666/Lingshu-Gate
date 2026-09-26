import type { McpServer, ToolDefinition } from "@/api/client"
import type { InvokeCopy } from "./copy"
import { createArgumentExample, schemaFields, validateArguments } from "./schema"
import { pathFor, type ValidationIssue } from "@/lib/validation"

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
export type PendingArgumentEntries = Record<string,string>
export type InvokeDraft = {text:string;mode:"form"|"json";source:"example"|"defaults"|"edited";declared:boolean;schemaVersion:string;error:string|null;pending:boolean;result:InvocationResult|null;revision:number;validationAttempted:boolean;initialText:string;pendingEntries:PendingArgumentEntries}
export const hasPendingArgumentEntries = (draft:Pick<InvokeDraft,"pendingEntries">) => Object.values(draft.pendingEntries).some(value=>value.length > 0)
export const invokeDraftIsDirty = (draft:InvokeDraft) => draft.text !== draft.initialText || hasPendingArgumentEntries(draft)
/** Parent replacement/removal must not orphan an unfinished map row. */
export function argumentChangeHidesPendingEntry(entries:PendingArgumentEntries,path:string[]) {
  return Object.entries(entries).some(([pointer,value])=>value.length > 0 && path.length <= pathFor(pointer).length && path.every((part,index)=>part === pathFor(pointer)[index]))
}
/** The only preparation entry point used by Run; unadded input is never omitted. */
export function prepareInvokeArguments(tool:ToolDefinition,draft:InvokeDraft,c:InvokeCopy) {
  if (hasPendingArgumentEntries(draft)) {
    const issues:ValidationIssue[]=Object.entries(draft.pendingEntries).filter(([,value])=>value.length > 0).map(([path])=>({code:"pendingEntry",messageKey:"pendingEntryHint",message:c.pendingEntryHint,severity:"error",source:"domain",path,revision:draft.revision}))
    return {ok:false as const,error:c.pendingEntryHint,issues}
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
