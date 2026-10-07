import { expect, it } from "vitest"
import type { UserDownstreamCredential } from "@/api/client"
import { filterDownstreamCredentials } from "./downstream-credential-filters"
const rows: UserDownstreamCredential[] = [
 {server_id:"a",server_name:"文档服务",id:"pat",name:"Repository access",description:"Read project metadata",transport_type:"streamable_http",required:true,configured:false,injection:{type:"http_header",name:"Authorization",template:"Bearer {value}"}},
 {server_id:"b",server_name:"工单",id:"key",name:"API key",description:"Ticket access",transport_type:"streamable_http",required:false,configured:true,injection:{type:"http_header",name:"X-Api-Key",template:"{value}"}},
]
const all={query:"",server:"",status:"all",required:"all"}
it("searches service, purpose and header metadata, never a secret value",()=>{
 expect(filterDownstreamCredentials(rows,{...all,query:"metadata"})).toEqual([rows[0]])
 expect(filterDownstreamCredentials(rows,{...all,query:"文档"})).toEqual([rows[0]])
 expect(filterDownstreamCredentials(rows,{...all,query:"x-api"})).toEqual([rows[1]])
 expect(filterDownstreamCredentials(rows,{...all,query:"Bearer"})).toEqual([])
})
it("combines status, service and requirement filters without mutating source",()=>{
 expect(filterDownstreamCredentials(rows,{...all,status:"missing"})).toEqual([rows[0]])
 expect(filterDownstreamCredentials(rows,{...all,status:"configured",required:"optional",server:"b"})).toEqual([rows[1]])
 expect(filterDownstreamCredentials(rows,{...all,status:"configured",server:"a"})).toEqual([])
 expect(rows).toHaveLength(2)
})

it('distinguishes loading, failed, no match and no declared slot states',async()=>{
 const {downstreamEmptyState}=await import('./downstream-credential-filters')
 expect(downstreamEmptyState(200,false,false)).toBe('noCurrentMatches')
 expect(downstreamEmptyState(0,false,false)).toBe('empty')
 expect(downstreamEmptyState(0,true,false)).toBe('loadingData')
 expect(downstreamEmptyState(0,false,true)).toBe('notLoaded')
})
