import type { BuildFailureHint } from "@/api/builds"
import type { MessageKey, TFunction } from "@/i18n"

const FAILURE_HINT_MESSAGES: Record<string, { title: MessageKey; suggestion: MessageKey }> = {
  command_not_found: { title: "buildHintCommandNotFoundTitle", suggestion: "buildHintCommandNotFoundSuggestion" },
  command_timeout: { title: "buildHintCommandTimeoutTitle", suggestion: "buildHintCommandTimeoutSuggestion" },
  unsupported_runtime: { title: "buildHintUnsupportedRuntimeTitle", suggestion: "buildHintUnsupportedRuntimeSuggestion" },
  runtime_not_detected: { title: "buildHintGenericTitle", suggestion: "buildHintGenericSuggestion" },
  node_entrypoint_missing: { title: "buildHintNodeEntrypointTitle", suggestion: "buildHintNodeEntrypointSuggestion" },
  python_entrypoint_missing: { title: "buildHintPythonEntrypointTitle", suggestion: "buildHintPythonEntrypointSuggestion" },
  install_failed: { title: "buildHintInstallFailedTitle", suggestion: "buildHintInstallFailedSuggestion" },
  build_script_failed: { title: "buildHintBuildScriptFailedTitle", suggestion: "buildHintBuildScriptFailedSuggestion" },
  cancelled: { title: "buildHintCancelledTitle", suggestion: "buildHintCancelledSuggestion" },
  build_failed: { title: "buildHintGenericTitle", suggestion: "buildHintGenericSuggestion" },
}

export function formatCommand(command: unknown) {
  if (Array.isArray(command)) return command.map((item) => String(item)).join(" ")
  return typeof command === "string" ? command : JSON.stringify(command)
}

export { formatDateTime } from "@/lib/utils"

export function shortId(value: string | null | undefined, head = 8) {
  const text = value || ""
  return text.length > head ? `${text.slice(0, head)}…` : text
}

export function localizeFailureHint(t: TFunction, hint: BuildFailureHint | null | undefined) {
  if (!hint) return null
  const message = FAILURE_HINT_MESSAGES[hint.code] || FAILURE_HINT_MESSAGES.build_failed
  return {
    code: hint.code,
    title: t(message.title),
    suggestion: t(message.suggestion),
  }
}

export async function copyText(value: string | null | undefined) {
  const text = value || ""
  if (!text) return false
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}
