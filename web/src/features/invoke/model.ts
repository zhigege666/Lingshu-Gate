import type { McpServer, ToolDefinition } from "@/api/client"
import type { InvokeCopy } from "./copy"
import { createArgumentExample, schemaFields } from "./schema"

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
export type InvokeDraft = {text:string;mode:"form"|"json";source:"example"|"defaults"|"edited";declared:boolean;schemaVersion:string;error:string|null;pending:boolean;result:InvocationResult|null}
export function createInvokeDraft(tool: ToolDefinition): InvokeDraft {
  const example=createArgumentExample(tool.input_schema)
  return {...example,mode:schemaFields(tool.input_schema) ? "form" : "json",source:"example",schemaVersion:JSON.stringify(tool.input_schema),error:null,pending:false,result:null}
}
export function updateDraft(drafts: Record<string,InvokeDraft>,key:string,initial:InvokeDraft,changes:Partial<InvokeDraft>) {
  return {...drafts,[key]:{...(drafts[key] || initial),...changes}}
}
export function responseSucceeded(response: unknown): boolean {
  if (!response || typeof response !== "object") return true
  const result=response as {ok?:boolean;isError?:boolean;output?:{isError?:boolean}}
  return result.ok !== false && result.isError !== true && result.output?.isError !== true
}
