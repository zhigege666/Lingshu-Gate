/** Shared diagnostics for editable documents; domain adapters supply messages. */
export const JSON_SOURCE_MESSAGE = {
  "zh-CN": {
    duplicate_key: "同一 JSON 对象中出现重复字段。请保留唯一的字段名；当前原文已保留。",
    unsafe_integer: "JSON 整数超出可安全编辑的范围。请按接口支持的类型修正，避免数字被舍入；当前原文已保留。",
    non_finite_number: "JSON 数值超出可表示范围。请修正该数值；当前原文已保留。",
  },
  en: {
    duplicate_key: "An object contains duplicate JSON keys. Keep one value for each key; the original text is retained.",
    unsafe_integer: "A JSON integer is outside the safe editing range. Correct it using a type supported by the API to avoid rounding; the original text is retained.",
    non_finite_number: "A JSON number is outside the representable range. Correct the value; the original text is retained.",
  },
} as const

export const JSON_SYNTAX_MESSAGE = {
  "zh-CN": "JSON 格式有误，请检查引号、逗号和括号。当前输入已保留。",
  en: "Invalid JSON. Check quotes, commas and brackets. Your input has been retained.",
} as const

export type ValidationIssue = {
  code: string
  messageKey: string
  message: string
  severity: "error" | "warning"
  source: "syntax" | "schema" | "domain" | "server"
  path: string
  revision: number
  range?: { start: number; end: number }
}

export const pointerFor = (path: string[]) => path.length ? `/${path.map(part => part.replace(/~/g, "~0").replace(/\//g, "~1")).join("/")}` : ""
export const pathFor = (pointer: string) => pointer ? pointer.slice(1).split("/").map(part => part.replace(/~1/g, "/").replace(/~0/g, "~")) : []
