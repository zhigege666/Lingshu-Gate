import { describe, expect, it } from "vitest"
import { readableResult, resultMatches, resultWindow } from "./result-model"

describe("read-only invocation result presentation", () => {
  it("decodes MCP JSON-in-text once and retains raw input untouched", () => {
    const raw=JSON.stringify({ duration_ms:126, result:{ content:[{type:"text",text:JSON.stringify({items:[{title:"知识库"}]})}],isError:false } })
    const result=readableResult(raw)
    expect(result.value).toEqual({items:[{title:"知识库"}]})
    expect(result.duration).toBe(126)
    expect(result.text).not.toContain('\\"items')
    expect(JSON.parse(raw).result.content[0].text).toContain('"items"')
  })
  it("retains failure flags, structured content and multiple text blocks", () => {
    const result=readableResult(JSON.stringify({error:"transport warning",result:{isError:true,content:[{type:"text",text:"plain"},{type:"text",text:'{"code":403}'}],structuredContent:{denied:true}}}))
    expect(result.text).toContain('"isError": true')
    expect(result.text).toContain('"code": 403')
    expect(result.text).toContain('transport warning')
  })
  it.each(["", "plain text", "<script>alert(1)</script>", "{invalid}"])("preserves non-JSON text without interpreting markup: %s", raw => {
    expect(readableResult(raw).text).toBe(raw)
    expect(readableResult(raw).structured).toBe(false)
  })
  it("searches literally, including punctuation, CJK, zero matches and capped repeats", () => {
    expect(resultMatches("A.b a.B", "a.b").positions).toEqual([0,4])
    expect(resultMatches("工具 工具", "工具").positions).toEqual([0,3])
    expect(resultMatches("abc", "").positions).toEqual([])
    expect(resultMatches("abc", "missing").positions).toEqual([])
    expect(resultMatches("aaaa", "a", 2)).toEqual({positions:[0,1],capped:true})
  })
  it("searches and locates beyond a bounded large-result display window", () => {
    const text="x".repeat(90000)+"needle"+"x".repeat(90000)
    const offset=resultMatches(text,"needle").positions[0]
    const window=resultWindow(text,offset)
    expect(window.text.length).toBe(32000)
    expect(window.text).toContain("needle")
    expect(window.start).toBeGreaterThan(0)
    expect(window.end).toBeLessThan(text.length)
  })
})

it("keeps match offsets in the original text when case conversion changes Unicode length",()=>{
 expect(resultMatches("İabc", "abc").positions).toEqual([1])
 expect(resultMatches("literal [a]+", "[a]+").positions).toEqual([8])
})
