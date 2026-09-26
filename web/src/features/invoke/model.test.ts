import { describe,expect,it } from "vitest"
import type { McpServer,ToolDefinition } from "@/api/client"
import { invokeCopy } from "./copy"
import { createInvokeDraft,draftKey,responseSucceeded,serviceOptions,toolServiceKey,updateDraft } from "./model"
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
})
