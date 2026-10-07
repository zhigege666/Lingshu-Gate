import { expect, it } from "vitest"
import { classificationOrder } from "./tool-classifications-page"
import type { ToolClassification } from "@/api/client"
it("orders confirmation, publish, published and stale queues without mutating source",()=>{
 const items = [{id:"stale",status:"stale",effective_access:"unknown"},{id:"published",status:"published",effective_access:"read"},{id:"reviewed",status:"pending",effective_access:"read"},{id:"new",status:"pending",effective_access:"unknown"}] as ToolClassification[]
 expect([...items].sort((a,b)=>classificationOrder(a)-classificationOrder(b)).map(x=>x.id)).toEqual(["new","reviewed","published","stale"])
 expect(items[0].id).toBe("stale")
})
