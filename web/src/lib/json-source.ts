/** Source checks that JSON.parse cannot perform after keys or numbers are changed. */
export type JsonSourceErrorCode = "duplicate_key" | "unsafe_integer" | "non_finite_number"
export type JsonSourceRange = { start: number; end: number }

const messages: Record<JsonSourceErrorCode, string> = {
  duplicate_key: "JSON contains a duplicate object key.",
  unsafe_integer: "JSON contains an integer outside the safe numeric range.",
  non_finite_number: "JSON contains a number outside the finite numeric range.",
}

export class JsonSourceError extends Error {
  readonly code: JsonSourceErrorCode
  /** JSON Pointer; an empty string identifies the root value. */
  readonly path: string
  /** UTF-16 offsets into the unchanged source, with an exclusive end. */
  readonly range: JsonSourceRange

  constructor(code: JsonSourceErrorCode, path: string, range: JsonSourceRange) {
    // Do not include source text or numeric/secret values in an error message.
    super(messages[code])
    this.name = "JsonSourceError"
    this.code = code
    this.path = path
    this.range = range
  }
}

type SourcePath = { parent: SourcePath | null; key: string }
type Frame = { path: SourcePath | null } & (
  | { kind: "object"; keys: Set<string>; key: string; expectingKey: boolean }
  | { kind: "array"; index: number }
)

function pointer(path: SourcePath | null): string {
  const parts: string[] = []
  for (let current = path; current; current = current.parent) {
    parts.push(current.key.replace(/~/g, "~0").replace(/\//g, "~1"))
  }
  return parts.length ? "/" + parts.reverse().join("/") : ""
}

/**
 * Parse an editable JSON source, rejecting duplicate keys, nonfinite numbers,
 * and unsafe integers before returning a semantic value. Native SyntaxError is
 * retained for malformed JSON. Keys are compared after JSON escape decoding.
 *
 * Callers own the raw text: a failure must retain it and block conversion/write,
 * never substitute a previous successful value. This does not validate a domain
 * schema or provide arbitrary decimal precision; ordinary fractions keep the
 * existing JavaScript Number semantics. No strings or values are rewritten.
 */
export function parseJsonSource(text: string): unknown {
  // Native parsing validates the grammar. The source scan below must finish
  // before its result can escape, including when native parsing rounded a value.
  const parsed: unknown = JSON.parse(text)
  const frames: Frame[] = []
  const numberPattern = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y
  let offset = 0
  const valuePath = (): SourcePath | null => {
    const parent = frames.at(-1)
    return parent ? { parent: parent.path, key: parent.kind === "array" ? String(parent.index) : parent.key } : null
  }
  const fail = (code: JsonSourceErrorCode, path: SourcePath | null, start: number, end: number): never => {
    throw new JsonSourceError(code, pointer(path), { start, end })
  }

  // Iterative frames avoid introducing a smaller nesting limit than JSON.parse.
  // Paths are linked and are materialized only for a diagnostic.
  while (offset < text.length) {
    const character = text[offset]
    if (character === '"') {
      const start = offset++
      while (offset < text.length) {
        const next = text[offset++]
        if (next === '"') break
        if (next === "\\") offset++
      }
      const parent = frames.at(-1)
      if (parent?.kind === "object" && parent.expectingKey) {
        const key = JSON.parse(text.slice(start, offset)) as string
        if (parent.keys.has(key)) fail("duplicate_key", { parent: parent.path, key }, start, offset)
        parent.keys.add(key)
        parent.key = key
        parent.expectingKey = false
      }
    } else if (character === "{") {
      frames.push({ kind: "object", path: valuePath(), keys: new Set(), key: "", expectingKey: true })
      offset++
    } else if (character === "[") {
      frames.push({ kind: "array", path: valuePath(), index: 0 })
      offset++
    } else if (character === "}" || character === "]") {
      frames.pop()
      offset++
    } else if (character === ",") {
      const parent = frames.at(-1)!
      if (parent.kind === "object") parent.expectingKey = true
      else parent.index++
      offset++
    } else if (character === "-" || character >= "0" && character <= "9") {
      const start = offset
      numberPattern.lastIndex = offset
      const token = numberPattern.exec(text)![0]
      offset += token.length
      const value = Number(token)
      if (!Number.isFinite(value)) fail("non_finite_number", valuePath(), start, offset)
      if (Number.isInteger(value) && !Number.isSafeInteger(value)) fail("unsafe_integer", valuePath(), start, offset)
    } else {
      // Whitespace, a colon, or a true/false/null character; grammar is valid.
      offset++
    }
  }
  return parsed
}
