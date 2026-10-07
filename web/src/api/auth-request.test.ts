import { afterEach, describe, expect, it, vi } from "vitest"
import { authRequest, AUTH_REQUEST_TIMEOUT_MS } from "./auth-request"
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals()})
describe("bounded authentication requests",()=>{
 it.each([401,503])("preserves HTTP %s for session-state decisions",async status=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:"not ready"}),{status})))
  await expect(authRequest("/v1/auth/me")).rejects.toMatchObject({status,timedOut:false})
 })
 it("rejects malformed success bodies",async()=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response("<html>failure</html>")))
  await expect(authRequest("/v1/auth/me")).rejects.toMatchObject({status:200})
 })
 it.each(["headers","body"])("times out stalled %s without replaying a write",async phase=>{
  vi.useFakeTimers()
  const never=new Promise(()=>{})
  const fetcher=vi.fn().mockReturnValue(phase==="headers"?never:Promise.resolve({ok:true,status:200,text:()=>never}))
  vi.stubGlobal("fetch",fetcher)
  const pending=authRequest("/v1/auth/logout",{})
  const assertion=expect(pending).rejects.toMatchObject({timedOut:true})
  await vi.advanceTimersByTimeAsync(AUTH_REQUEST_TIMEOUT_MS)
  await assertion
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
 })
})
