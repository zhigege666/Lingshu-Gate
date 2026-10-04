import { describe, expect, it } from "vitest"
import { privateHttpOrigin } from "./http-trust"

describe("private HTTP declarations", () => {
  it("uses exact canonical RFC1918 IPv4 and the actual port", () => {
    expect(privateHttpOrigin("http://10.23.45.67/mcp")).toEqual({ ip: "10.23.45.67", port: 80 })
    expect(privateHttpOrigin("http://172.16.0.1:8080/mcp")).toEqual({ ip: "172.16.0.1", port: 8080 })
    expect(privateHttpOrigin("http://192.168.1.2:3000/mcp")).toEqual({ ip: "192.168.1.2", port: 3000 })
  })
  it.each(["http://10.023.45.67/mcp", "http://167772161/mcp", "http://0x0a000001/mcp", "http://169.254.169.254/mcp", "http://100.100.100.200/mcp", "http://192.0.0.8/mcp", "http://172.32.0.1/mcp", "http://8.8.8.8/mcp", "http://private.example.test/mcp", "http://user:synthetic@10.0.0.1/mcp", "http://10.0.0.1/mcp?", "http://10.0.0.1/mcp#", "http://10.0.0.1:0/mcp", "http://[::ffff:10.0.0.1]/mcp", "https://10.0.0.1/mcp"])("does not offer private HTTP trust for %s", endpoint => {
    expect(privateHttpOrigin(endpoint)).toBeNull()
  })
})
