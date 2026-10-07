import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"
import { ConnectionGuide, ConnectionGuideChecks } from "./connection-guide"
import { emptyConnection } from "./model"
it.each([true,false])("keeps all four setup steps and external configuration instructions visible (%s)",zh=>{
 for(let step=0;step<4;step++){
  const html=renderToStaticMarkup(<ConnectionGuide zh={zh} step={step} onStep={()=>{}} disabled={false}><div>CONFIGURATION_FIELDS</div></ConnectionGuide>)
  expect(html).toContain("CONFIGURATION_FIELDS")
  expect(html).toContain(zh?"在哪里找配置":"Where to find the settings")
  if(step===0){expect(html).toContain("Networking");expect(html).not.toContain("credential:ID")}
  if(step===1){expect(html).toContain("jwks_uri");expect(html).toContain("RS256")}
  if(step===3){expect(html).toContain("Security and login");expect(html).toContain("401")}
 }
})
it("does not label local configuration checks as verified ChatGPT connectivity",()=>{
 const html=renderToStaticMarkup(<ConnectionGuideChecks draft={emptyConnection} zh />)
 expect(html).toContain("配置仍有缺项")
 expect(html).toContain("尚未验证外部连通与 ChatGPT 调用")
})

it("shows only the selected network instructions",()=>{
 const tunnel=renderToStaticMarkup(<ConnectionGuide zh step={0} mode="secure_mcp_tunnel" onStep={()=>{}} disabled={false}>fields</ConnectionGuide>)
 expect(tunnel).toContain("credential:ID")
 expect(tunnel).not.toContain("Service URL")
})
