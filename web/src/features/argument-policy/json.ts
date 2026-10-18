/** Bounded JSON input for policy values; preserves text until explicitly submitted. */
export class PolicyJsonError extends Error {
  constructor(public code: string, public offset: number) { super(code) }
}

function decimalIdentity(token: string): string {
  const [mantissa, exponent = "0"] = token.toLowerCase().split("e")
  const negative = mantissa.startsWith("-")
  const unsigned = negative ? mantissa.slice(1) : mantissa
  const [whole, fraction = ""] = unsigned.split(".")
  const digits = (whole + fraction).replace(/^0+/, "")
  if (!digits) return "0"
  const trimmed = digits.replace(/0+$/, "")
  return (negative ? "-" : "") + trimmed + "e" + (Number(exponent) - fraction.length + digits.length - trimmed.length)
}

/** Reject duplicate members, nonfinite/rounded numbers, lone surrogates and deep input. */
export function parsePolicyJson(text: string, maxBytes = 65_536, limits: { maxDepth?: number; maxNodes?: number } = {}): unknown {
  let offset = 0, nodes = 0
  const maxNodes = limits.maxNodes ?? 8192, maxDepth = limits.maxDepth ?? 24
  const fail = (code = "json_syntax"): never => { throw new PolicyJsonError(code, offset) }
  if (text.length > maxBytes || new TextEncoder().encode(text).length > maxBytes) fail("json_limit")
  const space = () => { while (offset < text.length && /[ \t\n\r]/.test(text[offset])) offset++ }
  const string = (): string => {
    const start = offset++
    while (offset < text.length) {
      const character = text[offset++]
      if (character === '"') {
        let result: string
        try { result = JSON.parse(text.slice(start, offset)) as string } catch { return fail() }
        for (const point of result) {
          const code = point.charCodeAt(0)
          if (point.length === 1 && code >= 0xd800 && code <= 0xdfff) fail("json_unicode")
        }
        return result
      }
      if (character === "\\") { if (offset >= text.length) fail(); offset++ }
      else if (character.charCodeAt(0) < 32) fail()
    }
    return fail()
  }
  const value = (depth: number): unknown => {
    space()
    if (++nodes > maxNodes) fail("json_limit")
    if (depth > maxDepth) fail("json_depth")
    const character = text[offset]
    if (character === '"') return string()
    if (character === "{") {
      offset++; space()
      const result: Record<string, unknown> = {}, keys = new Set<string>()
      if (text[offset] === "}") { offset++; return result }
      while (offset < text.length) {
        space()
        if (text[offset] !== '"') fail()
        const key = string()
        if (++nodes > maxNodes) fail("json_limit")
        if (keys.has(key)) fail("json_duplicate")
        keys.add(key); space()
        if (text[offset++] !== ":") fail()
        Object.defineProperty(result, key, { value: value(depth + 1), enumerable: true, configurable: true, writable: true })
        space()
        const ending = text[offset++]
        if (ending === "}") return result
        if (ending !== ",") fail()
      }
      return fail()
    }
    if (character === "[") {
      offset++; space()
      const result: unknown[] = []
      if (text[offset] === "]") { offset++; return result }
      while (offset < text.length) {
        result.push(value(depth + 1)); space()
        const ending = text[offset++]
        if (ending === "]") return result
        if (ending !== ",") fail()
      }
      return fail()
    }
    for (const [literal, result] of [["true", true], ["false", false], ["null", null]] as const) {
      if (text.startsWith(literal, offset)) { offset += literal.length; return result }
    }
    const token = text.slice(offset).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/)?.[0]
    if (!token) return fail()
    offset += token.length
    const number = Number(token)
    if (!Number.isFinite(number) || Number.isInteger(number) && !Number.isSafeInteger(number)
      || decimalIdentity(token) !== decimalIdentity(JSON.stringify(number))) fail("json_number")
    return number
  }
  const result = value(0)
  space()
  if (offset !== text.length) fail()
  return result
}
