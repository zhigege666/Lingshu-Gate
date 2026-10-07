export type ToolDiscoveryMode = "direct" | "on_demand"
export type McpClientSettings = { name: string; endpoint: string; mode: ToolDiscoveryMode }

export function clientEndpoint(settings: McpClientSettings): string {
  if (!/^[a-zA-Z0-9_-]{1,64}$/.test(settings.name)) throw new Error("client_name_invalid")
  const url = new URL(settings.endpoint)
  if (!(["http:", "https:"].includes(url.protocol)) || url.username || url.password || url.hash || url.pathname !== "/mcp"
      || [...url.searchParams.keys()].some(key => key !== "tool_mode")) throw new Error("client_endpoint_invalid")
  if (settings.mode === "on_demand") url.searchParams.set("tool_mode", "on_demand")
  else url.searchParams.delete("tool_mode")
  return url.toString()
}

export function clientConfiguration(settings: McpClientSettings): string {
  return JSON.stringify({ mcpServers: { [settings.name]: { type: "http", url: clientEndpoint(settings), headers: { Authorization: "Bearer <YOUR_GATE_TOKEN>" } } } }, null, 2)
}
