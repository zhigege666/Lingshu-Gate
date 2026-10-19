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
  it("renders raw numeric drafts with an associated error and explicit recovery",()=>{
    const schema={type:"object",properties:{count:{type:"integer",description:"Number of records."}}}
    const html=renderToStaticMarkup(<ArgumentForm schema={schema} value={{count:7}} disabled={false} c={c} onChange={()=>{}} onJSON={()=>{}} pendingEntries={{"/count":{kind:"number",raw:"1e"}}} onPendingEntryChange={()=>{}}/>)
    const input=(html.match(/<input\b[^>]*>/g) || []).find(item=>item.includes(`id="${argumentFieldId(["count"])}"`))
    expect(input).toContain('type="text"')
    expect(input).toContain('inputMode="numeric"')
    expect(input).toContain('value="1e"')
    expect(input).toContain('aria-invalid="true"')
    expect(input).toContain(`aria-describedby="${argumentFieldId(["count"])}-help ${argumentFieldId(["count"])}-error"`)
    expect(html).toContain("Enter a complete safe integer")
    expect(html).toContain("Clear numeric draft")
  })
  it("does not interpret retained numeric text as a map name after its schema changes",()=>{
    const schema={type:"object",properties:{count:{type:"object",additionalProperties:{type:"string"}}}}
    const html=renderToStaticMarkup(<ArgumentForm schema={schema} value={{}} disabled={false} c={c} onChange={()=>{}} onJSON={()=>{}} pendingEntries={{"/count":{kind:"number",raw:"1e"}}} onPendingEntryChange={()=>{}}/>)
    const input=(html.match(/<input\b[^>]*>/g) || []).find(item=>item.includes(`id="${argumentFieldId(["count"])}"`))
    expect(input).toContain('value=""')
    expect(input).toContain('readOnly=""')
    expect(input).toContain(`aria-describedby="${argumentFieldId(["count"])}-pending-kind"`)
    const buttons=html.match(/<button\b[^>]*>[\s\S]*?<\/button>/g) || []
    expect(buttons.find(button=>button.includes(c.addKey))).toContain('disabled=""')
    expect(html).toContain("The schema changed")
    expect(html).toContain("<code>1e</code>")
    expect(html).toContain("Clear numeric draft")
  })
  it("keeps an unfinished map name separate when the field changes to a number",()=>{
    const schema={type:"object",properties:{count:{type:"number"}}}
    const html=renderToStaticMarkup(<ArgumentForm schema={schema} value={{}} disabled={false} c={c} onChange={()=>{}} onJSON={()=>{}} pendingEntries={{"/count":"1e"}} onPendingEntryChange={()=>{}}/>)
    const input=(html.match(/<input\b[^>]*>/g) || []).find(item=>item.includes(`id="${argumentFieldId(["count"])}"`))
    expect(input).toContain('value=""')
    expect(input).toContain('readOnly=""')
    expect(html).toContain("<code>1e</code>")
    expect(html).toContain(c.clearPendingEntry)
  })
  it("does not offer a non-null action when null is the only enum choice",()=>{
    const html=render({type:"object",properties:{choice:{type:["integer","null"],enum:[null]}}},{choice:null})
    expect(html).not.toContain(c.setValue)
  })
  it.each([
    [{type:"boolean"}, false, "false"],
    [{type:"integer",enum:[0,1]}, 0, "0"],
    [{type:["string","null"],enum:[null,"value"]}, null, "null"],
  ])("keeps typed short choices visible, including false, zero and null", (field, value, encoded) => {
    const html=render({type:"object",properties:{choice:field}},{choice:value})
    const radios=html.match(/<input\b[^>]*type="radio"[^>]*>/g) || []
    expect(radios).toHaveLength(2)
    expect(radios.filter(radio=>radio.includes('checked=""'))).toHaveLength(1)
    expect(radios.find(radio=>radio.includes('checked=""'))).toContain(`value="${encoded}"`)
    expect(html).toContain('role="radiogroup" aria-label="choice"')
    expect(html).toContain(`id="${argumentFieldId(["choice"])}"`)
  })
  it("does not silently set absent optional boolean values", () => {
    const html=render({type:"object",properties:{enabled:{type:"boolean"}}},{})
    expect(html.match(/type="radio"/g)).toHaveLength(2)
    expect(html).not.toContain('checked=""')
  })
  it("retains a popup selector for long fixed choices", () => {
    const html=render({type:"object",properties:{choice:{type:"string",enum:["A lengthy choice that cannot fit in a compact control", "Another lengthy choice that needs readable wrapping"]}}},{})
    expect(html).toContain('role="combobox"')
    expect(html).not.toContain('type="radio"')
  })
})
