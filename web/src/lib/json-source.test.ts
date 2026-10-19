import { describe, expect, it } from "vitest"
import { JsonSourceError, parseJsonSource } from "./json-source"

function sourceError(text: string): JsonSourceError {
  try { parseJsonSource(text) } catch (error) {
    expect(error).toBeInstanceOf(JsonSourceError)
    return error as JsonSourceError
  }
  throw new Error("Expected a JSON source error")
}

describe("editable JSON source preservation", () => {
  it("accepts ordinary JSON values, decimals, safe integer boundaries and numeric exponent forms", () => {
    const source = '{"values":[false,null,"",0,-0,0.1,0.2,123.45,1.2300,1e-7,1.25e2,1.5e12,9007199254740991,-9007199254740991,900719925474099100e-2,0e400],"nested":{"empty":[]}}'
    expect(parseJsonSource(source)).toEqual(JSON.parse(source))
    expect(Object.is(parseJsonSource("-0"), -0)).toBe(true)
  })

  it("does not interpret source-like text inside strings or confuse keys from separate objects", () => {
    const value = { "9007199254740993": "1e400", text: '{"key":1,"key":2}', escaped: 'a \\"quoted" value', rows: [{ id: 1 }, { id: 2 }], nested: { id: 3 } }
    expect(parseJsonSource(JSON.stringify(value))).toEqual(value)
  })

  it("rejects duplicate keys before the last value can replace the first", () => {
    const source = '{"settings":{"enabled":true,"enabled":false}}'
    const error = sourceError(source)
    expect(error.code).toBe("duplicate_key")
    expect(error.path).toBe("/settings/enabled")
    expect(error.range).toEqual({ start: source.lastIndexOf('"enabled"'), end: source.lastIndexOf('"enabled"') + '"enabled"'.length })
  })

  it("compares escaped keys by decoded value and reports escaped pointers through arrays", () => {
    const source = String.raw`{"a/b":[{"~x":1,"\u007ex":2}]}`
    const error = sourceError(source)
    expect(error.code).toBe("duplicate_key")
    expect(error.path).toBe("/a~1b/0/~0x")
    expect(source.slice(error.range.start, error.range.end)).toBe(String.raw`"\u007ex"`)
    expect(sourceError('{"":0,"":1}').path).toBe("/")
  })

  it.each([
    "9007199254740992", "9007199254740993", "-9007199254740993",
    "1e16", "-1e16", "9.007199254740992e15", "90071992547409930e-1",
    "9007199254740992.0", "1.25e20", "1e308",
  ])("rejects unsafe integer literal %s with its exact source range", token => {
    const source = `{"rows":[{}, {"id":${token}}]}`
    const error = sourceError(source)
    expect(error.code).toBe("unsafe_integer")
    expect(error.path).toBe("/rows/1/id")
    expect(source.slice(error.range.start, error.range.end)).toBe(token)
  })

  it.each(["1e400", "-1e400", "1.7976931348623159e308", "1e99999999"])("rejects nonfinite number %s", token => {
    const error = sourceError(token)
    expect(error.code).toBe("non_finite_number")
    expect(error.path).toBe("")
    expect(error.range).toEqual({ start: 0, end: token.length })
  })

  it("keeps prototype-named keys as ordinary own properties", () => {
    const parsed = parseJsonSource('{"__proto__":{"marker":true},"constructor":1}') as Record<string, unknown>
    expect(Object.getPrototypeOf(parsed)).toBe(Object.prototype)
    expect(Object.hasOwn(parsed, "__proto__")).toBe(true)
    expect(parsed.__proto__).toEqual({ marker: true })
    expect(parsed.constructor).toBe(1)
    expect(sourceError('{"__proto__":1,"__proto__":2}').code).toBe("duplicate_key")
  })

  it("does not add a recursive call-stack limit for otherwise valid JSON", () => {
    const depth = 3000
    let value = parseJsonSource("[".repeat(depth) + "0" + "]".repeat(depth))
    for (let index = 0; index < depth; index++) value = (value as unknown[])[0]
    expect(value).toBe(0)
    expect(sourceError("[".repeat(depth) + "9007199254740993" + "]".repeat(depth)).path).toBe("/0".repeat(depth))
  })

  it.each(["", "{", "01", "[1,]", '{"a":true "a":false}', "NaN", "Infinity", "-Infinity"])("retains syntax failure for %s", source => {
    expect(() => parseJsonSource(source)).toThrow(SyntaxError)
  })

  it("does not place source text or adjacent secrets in source diagnostics", () => {
    const error = sourceError('{"secret":"synthetic-do-not-echo","count":9007199254740993}')
    expect(error.path).toBe("/count")
    expect(String(error)).not.toContain("synthetic-do-not-echo")
    expect(JSON.stringify(error)).not.toContain("synthetic-do-not-echo")
    expect(String(error)).not.toContain("9007199254740993")
  })
})
