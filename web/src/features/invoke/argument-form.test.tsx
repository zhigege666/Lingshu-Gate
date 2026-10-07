import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { ArgumentForm, argumentFieldId } from "./argument-form"
import { invokeCopy } from "./copy"
import type { Schema } from "./schema"
const c=invokeCopy("en-US")
const render=(schema:Schema,value:Record<string,unknown>)=>renderToStaticMarkup(<ArgumentForm schema={schema} value={value} disabled={false} c={c} onChange={()=>{}} onJSON={()=>{}} pendingEntries={{}} onPendingEntryChange={()=>{}}/>)

describe("argument form presentation boundaries",()=>{
  it("keeps array and map secrets masked using their complete property path",()=>{
    const schema={type:"object",properties:{tokens:{type:"array",items:{type:"string"}},headers:{type:"object",additionalProperties:{type:"string"}}}}
    const html=render(schema,{tokens:["test-token"],headers:{Authorization:"test-auth"}})
    expect(html.match(/type="password"/g)).toHaveLength(2)
    expect(html).toContain("Add item")
    expect(html).toContain("Add field")
  })
  it("retains unknown nested fields visibly and offers JSON inspection",()=>{
    const html=render({type:"object",properties:{filter:{type:"object",properties:{known:{type:"string"}}}}},{filter:{known:"hello",unknown:false}})
    expect(html).toContain("Undeclared fields are retained")
    expect(html).toContain("unknown")
    expect(html).toContain("Edit in JSON")
    expect(html).not.toContain(c.noDescription)
  })
  it("associates inline errors with their field and uses the escaped summary path",()=>{
    const schema={type:"object",properties:{"a/b":{type:"string"}}}
    const html=renderToStaticMarkup(<ArgumentForm schema={schema} value={{}} disabled={false} c={c} onChange={()=>{}} onJSON={()=>{}} pendingEntries={{}} onPendingEntryChange={()=>{}} issues={[{code:"required",messageKey:"requiredError",message:c.requiredError,severity:"error",source:"schema",path:"/a~1b",revision:2}]}/>)
    expect(html).toContain(`aria-describedby="${argumentFieldId(["a/b"])}-error"`)
    expect(html).toContain('aria-invalid="true"')
    expect(html).toContain(c.requiredError)
  })
  it("renders controlled unfinished map names with explicit Add/Clear recovery",()=>{
    const schema={type:"object",properties:{headers:{type:"object",additionalProperties:{type:"string"}}}}
    const html=renderToStaticMarkup(<ArgumentForm schema={schema} value={{}} disabled={false} c={c} onChange={()=>{}} onJSON={()=>{}} pendingEntries={{"/headers":"X-Example"}} onPendingEntryChange={()=>{}}/>)
    expect(html).toContain('value="X-Example"')
    expect(html).toContain(c.pendingEntryHint)
    expect(html).toContain(c.addKey)
    expect(html).toContain(c.clearPendingEntry)
    expect(html).toContain(`aria-describedby="${argumentFieldId(["headers"])}-pending-hint"`)
    const locked=renderToStaticMarkup(<ArgumentForm schema={schema} value={{}} disabled={true} c={c} onChange={()=>{}} onJSON={()=>{}} pendingEntries={{"/headers":"X-Example"}} onPendingEntryChange={()=>{}}/>)
    const buttons=locked.match(/<button\b[^>]*>[\s\S]*?<\/button>/g) || []
    expect(buttons.find(button=>button.includes(c.clearPendingEntry))).toContain('disabled=""')
  })
  it("does not offer a non-null action when null is the only enum choice",()=>{
    const html=render({type:"object",properties:{choice:{type:["integer","null"],enum:[null]}}},{choice:null})
    expect(html).not.toContain(c.setValue)
  })
})
