/** Shared diagnostics for editable documents; domain adapters supply messages. */
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
