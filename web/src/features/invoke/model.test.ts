import { describe,expect,it } from "vitest"
import type { McpServer,ToolDefinition } from "@/api/client"
import { invokeCopy } from "./copy"
import { argumentChangeHidesPendingEntry,changeInvokeArgument,createInvokeDraft,draftKey,hasPendingArgumentEntries,invokeDraftIsDirty,parseArgumentNumber,prepareInvokeArguments,responseSucceeded,serviceOptions,snapshotArguments,toolServiceKey,updateDraft, type InvokeDraft } from "./model"
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

describe("unfinished numeric argument drafts",()=>{
  const numericTool={...prod,input_schema:{type:"object",properties:{count:{type:"integer",default:7}}}}
  const numericDraft=(raw:string):InvokeDraft=>({...createInvokeDraft(numericTool),pendingEntries:{"/count":{kind:"number",raw}}})

  it.each(["-","+",".","0.","1e","1e-","1e400","9007199254740993","-9007199254740993","9.007199254740992e15","NaN","Infinity"," "])("keeps %j outside the semantic number until it is complete and safe",raw=>{
    expect(parseArgumentNumber(raw,false)).toEqual({ok:false})
    const draft=numericDraft(raw)
    expect(JSON.parse(draft.text)).toEqual({count:7})
    expect(invokeDraftIsDirty(draft)).toBe(true)
    expect(prepareInvokeArguments(numericTool,draft,c)).toMatchObject({ok:false,issues:[{code:"pendingNumber",source:"domain",path:"/count"}]})
  })

  it.each([
    ["",true,undefined],["0",true,0],["-3",true,-3],["9007199254740991",true,Number.MAX_SAFE_INTEGER],
    ["-9007199254740991",true,Number.MIN_SAFE_INTEGER],["0.25",false,0.25],[".5",false,0.5],["1e3",true,1000],["-1.2e-3",false,-0.0012],
  ] as const)("accepts complete numeric input %j without changing its type",(raw,integer,value)=>{
    expect(parseArgumentNumber(raw,integer)).toEqual({ok:true,value})
  })

  it("keeps a fractional value pending for an integer field",()=>{
    expect(parseArgumentNumber("1.5",true)).toEqual({ok:false})
    expect(parseArgumentNumber("1.5",false)).toEqual({ok:true,value:1.5})
  })

  it("commits zero and clears its pending text together, preserving unknown values",()=>{
    const initial={...createInvokeDraft(numericTool),text:'{"count":7,"unknown":{"off":false,"nil":null,"empty":""}}'}
    const key=draftKey(numericTool)
    let drafts=updateDraft({},key,initial,{pendingEntries:{"/count":{kind:"number",raw:"1e"}}})
    const before=drafts[key]
    const changed=changeInvokeArgument(before,["count"],0,"resolve-number")
    expect(changed.ok).toBe(true)
    if (!changed.ok) return
    drafts=updateDraft(drafts,key,initial,{text:changed.text,pendingEntries:changed.pendingEntries,source:"edited"})
    expect(drafts[key].revision).toBe(before.revision+1)
    expect(drafts[key].pendingEntries).toEqual({})
    expect(before.pendingEntries).toEqual({"/count":{kind:"number",raw:"1e"}})
    expect(prepareInvokeArguments(numericTool,drafts[key],c)).toMatchObject({ok:true,value:{count:0,unknown:{off:false,nil:null,empty:""}}})
  })

  it("allows explicit empty-input removal but does not let ordinary removal discard numeric text",()=>{
    const draft=numericDraft("-")
    expect(changeInvokeArgument(draft,["count"],undefined)).toEqual({ok:false,reason:"pending-entry"})
    const cleared=changeInvokeArgument(draft,["count"],undefined,"resolve-number")
    expect(cleared).toMatchObject({ok:true,text:"{}",pendingEntries:{}})
    expect(draft.pendingEntries).toEqual({"/count":{kind:"number",raw:"-"}})
  })

  it("keeps other names and numeric drafts while correcting one field",()=>{
    const draft:InvokeDraft={...numericDraft("-"),text:'{"group":{"count":7,"next":2}}',pendingEntries:{"/group/count":{kind:"number",raw:"-"},"/group/next":{kind:"number",raw:"1e"},"/group/headers":"X-Example"}}
    expect(changeInvokeArgument(draft,["group"],undefined)).toEqual({ok:false,reason:"pending-entry"})
    const changed=changeInvokeArgument(draft,["group","count"],0,"resolve-number")
    expect(changed).toMatchObject({ok:true,pendingEntries:{"/group/next":{kind:"number",raw:"1e"},"/group/headers":"X-Example"}})
    if (changed.ok) expect(JSON.parse(changed.text)).toEqual({group:{count:0,next:2}})
    const mapDraft={...draft,pendingEntries:{"/group/headers":"1e"}}
    expect(changeInvokeArgument(mapDraft,["group","headers"],0,"resolve-number")).toEqual({ok:false,reason:"pending-entry"})
  })

  it("retains numeric text and its revision across a schema refresh",()=>{
    const key=draftKey(numericTool),initial=createInvokeDraft(numericTool)
    let drafts=updateDraft({},key,initial,{pendingEntries:{"/count":{kind:"number",raw:"1e"}}})
    const changedSchema={...numericTool,input_schema:{type:"object",properties:{count:{type:"object",additionalProperties:{type:"string"}}}}}
    drafts=updateDraft(drafts,key,createInvokeDraft(changedSchema),{error:null})
    expect(drafts[key].pendingEntries).toEqual({"/count":{kind:"number",raw:"1e"}})
    expect(prepareInvokeArguments(changedSchema,drafts[key],c)).toMatchObject({ok:false,issues:[{code:"pendingNumber",path:"/count",revision:1}]})
  })

  it("does not renumber an array sibling that has unfinished input",()=>{
    const draft:InvokeDraft={...numericDraft("-"),text:'{"rows":[1,2]}',pendingEntries:{"/rows/0":{kind:"number",raw:"-"},"/rows/1":{kind:"number",raw:"1e"}}}
    expect(changeInvokeArgument(draft,["rows"],[2])).toEqual({ok:false,reason:"pending-entry"})
    expect(changeInvokeArgument(draft,["rows","0"],undefined,"resolve-number")).toEqual({ok:false,reason:"pending-entry"})
    const corrected=changeInvokeArgument(draft,["rows","0"],0,"resolve-number")
    expect(corrected).toMatchObject({ok:true,pendingEntries:{"/rows/1":{kind:"number",raw:"1e"}}})
    if (corrected.ok) expect(JSON.parse(corrected.text)).toEqual({rows:[0,2]})
  })

  it("never clears numeric text when the document or replacement is invalid",()=>{
    const draft=numericDraft("9007199254740993")
    for (const value of [Infinity,NaN,9007199254740992,null,{}]) expect(changeInvokeArgument(draft,["count"],value,"resolve-number")).toEqual({ok:false,reason:"invalid-number"})
    expect(changeInvokeArgument({...draft,text:'{"count":7,'},["count"],0,"resolve-number")).toEqual({ok:false,reason:"invalid-source"})
    expect(draft.pendingEntries).toEqual({"/count":{kind:"number",raw:"9007199254740993"}})
  })
})
