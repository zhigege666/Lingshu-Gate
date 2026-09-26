import { describe,expect,it } from "vitest"
import type { McpServer,ToolDefinition } from "@/api/client"
import { invokeCopy } from "./copy"
import { argumentChangeHidesPendingEntry,createInvokeDraft,draftKey,hasPendingArgumentEntries,invokeDraftIsDirty,prepareInvokeArguments,responseSucceeded,serviceOptions,snapshotArguments,toolServiceKey,updateDraft } from "./model"
const tool=(id:string,serverId:string):ToolDefinition=>({id,name:"Search",description:"",permission:"read",source:"mcp",metadata:{server_id:serverId},input_schema:{type:"object",properties:{query:{type:"string",examples:[serverId]}}}})
const prod=tool("mcp.prod.search","prod"),staging=tool("mcp.staging.search","staging")
const c=invokeCopy("en-US")
describe("service-scoped invocation state",()=>{
  it("separates same-name tools by stable service identity and registered ID",()=>{
    expect(draftKey(prod)).not.toBe(draftKey(staging))
    const groups=serviceOptions([prod,staging],[],c)
    expect(groups).toHaveLength(2)
    expect(groups.find(item=>item.key===toolServiceKey(prod))?.tools).toEqual([prod])
  })
  it("uses accessible catalog metadata without requiring service-management data",()=>{
    const groups=serviceOptions([prod],[],c)
    expect(groups[0].label).toBe("prod")
    const named=serviceOptions([prod],[{id:"prod",name:"Docs"},{id:"empty",name:"Empty"}] as McpServer[],c)
    expect(named[0].label).toBe("Docs · prod")
    expect(named[1].tools).toEqual([])
  })
  it("does not guess a service from dotted IDs or conflate built-in groups",()=>{
    const missing={...prod,metadata:{}}
    const builtin={...prod,source:"builtin"}
    expect(toolServiceKey(missing)).not.toBe(toolServiceKey(prod))
    expect(toolServiceKey(builtin)).not.toBe(toolServiceKey(prod))
  })
  it("routes a late result to its original draft without overwriting another service",()=>{
    const a=createInvokeDraft(prod),b=createInvokeDraft(staging)
    let drafts={[draftKey(prod)]:{...a,text:'{"query":"production draft"}'},[draftKey(staging)]:{...b,text:'{"query":"staging draft"}'}}
    drafts=updateDraft(drafts,draftKey(prod),a,{pending:true})
    drafts=updateDraft(drafts,draftKey(staging),b,{text:'{"query":"edited while waiting"}'})
    drafts=updateDraft(drafts,draftKey(prod),a,{pending:false,result:{ok:true,text:"result",toolId:prod.id,target:"prod"}})
    expect(drafts[draftKey(prod)].text).toContain("production draft")
    expect(drafts[draftKey(staging)].text).toContain("edited while waiting")
    expect(drafts[draftKey(staging)].result).toBeNull()
    expect(drafts[draftKey(prod)].result?.toolId).toBe(prod.id)
  })
  it("shows unsuccessful HTTP-success payloads as failures",()=>{
    expect(responseSucceeded({ok:false,error:"denied"})).toBe(false)
    expect(responseSucceeded({ok:true,output:{isError:true}})).toBe(false)
    expect(responseSucceeded({ok:true,output:{value:1}})).toBe(true)
  })
  it("undoes only parameters after a completed invocation and preserves its result",()=>{
    const original={...createInvokeDraft(prod),text:'{"query":"before defaults"}'}
    const snapshot=snapshotArguments(original)
    let drafts=updateDraft({},draftKey(prod),original,{text:"{}",source:"defaults"})
    drafts=updateDraft(drafts,draftKey(prod),original,{pending:true})
    const result={ok:true,text:"new response",toolId:prod.id,target:"prod"}
    drafts=updateDraft(drafts,draftKey(prod),original,{pending:false,result})
    drafts=updateDraft(drafts,draftKey(prod),original,snapshot)
    expect(drafts[draftKey(prod)].text).toBe(original.text)
    expect(drafts[draftKey(prod)].result).toBe(result)
    expect(drafts[draftKey(prod)].pending).toBe(false)
    expect(drafts[draftKey(prod)].revision).toBe(2)
    expect(snapshot).not.toHaveProperty("result")
    expect(snapshot).not.toHaveProperty("pending")
  })
  it("preserves initial draft identity and increments revision only for parameter text changes",()=>{
    const initial=createInvokeDraft(prod)
    const key=draftKey(prod)
    let drafts=updateDraft({},key,initial,{text:'{"query":"edited"}'})
    drafts=updateDraft(drafts,key,initial,{mode:"json",pending:true})
    expect(drafts[key].initialText).toBe(initial.text)
    expect(drafts[key].revision).toBe(1)
    expect(drafts[key].pending).toBe(true)
  })
  it("does not silently submit a valid document while a map key is still unfinished",()=>{
    const mapTool={...prod,input_schema:{type:"object",properties:{headers:{type:"object",additionalProperties:{type:"string"}}}}}
    const initial=createInvokeDraft(mapTool)
    const key=draftKey(mapTool)
    let drafts=updateDraft({},key,initial,{pendingEntries:{"/headers":"X-Example"}})
    expect(drafts[key].text).toBe(initial.text)
    expect(invokeDraftIsDirty(drafts[key])).toBe(true)
    expect(prepareInvokeArguments(mapTool,drafts[key],c)).toMatchObject({ok:false,issues:[{code:"pendingEntry",source:"domain",path:"/headers",revision:1}]})
    // A catalog/schema refresh keeps staged names outside the submitted document.
    drafts=updateDraft(drafts,key,createInvokeDraft({...mapTool,input_schema:{type:"object"}}),{error:null})
    expect(drafts[key].pendingEntries).toEqual({"/headers":"X-Example"})
    drafts=updateDraft(drafts,key,initial,{pendingEntries:{}})
    expect(hasPendingArgumentEntries(drafts[key])).toBe(false)
    expect(invokeDraftIsDirty(drafts[key])).toBe(false)
    expect(prepareInvokeArguments(mapTool,drafts[key],c)).toMatchObject({ok:true,value:{}})
  })
  it("retains unfinished names under their tool and blocks ancestor edits that hide them",()=>{
    const a=createInvokeDraft(prod),b=createInvokeDraft(staging)
    let drafts=updateDraft({},draftKey(prod),a,{pendingEntries:{"/rows/1/headers":"X-Example"}})
    drafts=updateDraft(drafts,draftKey(staging),b,{text:'{"query":"other"}'})
    expect(drafts[draftKey(prod)].pendingEntries).toEqual({"/rows/1/headers":"X-Example"})
    expect(drafts[draftKey(staging)].pendingEntries).toEqual({})
    expect(argumentChangeHidesPendingEntry(drafts[draftKey(prod)].pendingEntries,["rows"])).toBe(true)
    expect(argumentChangeHidesPendingEntry(drafts[draftKey(prod)].pendingEntries,["rows","1","headers"])).toBe(true)
    expect(argumentChangeHidesPendingEntry(drafts[draftKey(prod)].pendingEntries,["rows","1","headers","X-Example"])).toBe(false)
    expect(argumentChangeHidesPendingEntry({"/ab":"unfinished"},["a"])).toBe(false)
  })
})
