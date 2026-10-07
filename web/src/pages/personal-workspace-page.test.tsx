import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { PersonalWorkspacePage, initialPersonalWorkspaceView, personalToolAccessLabel, personalCallLabel } from "@/pages/personal-workspace-page"
import { translate, type TFunction } from "@/i18n"
const t: TFunction = key => translate("en-US", key)
const props = { locale: "en-US" as const, t, onNavigate: () => {}, onInvoke: () => {} }

describe("personal workspace presentation", () => {
  it("localizes recorded decisions and outcomes without changing unknown values", () => {
    expect(personalCallLabel("allow", "zh-CN")).toBe("允许")
    expect(personalCallLabel("deny", "en-US")).toBe("Denied")
    expect(personalCallLabel("not_invoked", "zh-CN")).toBe("未执行")
    expect(personalCallLabel("unrecognized", "en-US")).toBe("unrecognized")
  })
  it("uses human readable access labels and does not treat unknown access as a grant", () => {
    expect(personalToolAccessLabel("read", "zh-CN")).toBe("只读")
    expect(personalToolAccessLabel("write", "zh-CN")).toBe("读写")
    expect(personalToolAccessLabel("read", "en-US")).toBe("Read only")
    expect(personalToolAccessLabel("write", "en-US")).toBe("Read and write")
    expect(personalToolAccessLabel("unexpected", "zh-CN")).toBe("待确认")
  })
  it("restores search from the owning user's navigation snapshot", () => {
    const html = renderToStaticMarkup(<PersonalWorkspacePage {...props} view="myServers" viewState={{ ...initialPersonalWorkspaceView, query: "synthetic-service", page: 3 }} />)
    expect(html).toContain('value="synthetic-service"')
    expect(html).not.toContain("Save and restart")
  })
  it("labels the personal audit loaded range rather than implying a complete history", () => {
    const html = renderToStaticMarkup(<PersonalWorkspacePage {...props} view="myInvocations" />)
    expect(html).toContain("up to 500 loaded, not an all-time total")
  })
  it("defaults to built-in grants and requires Gate confirmation within existing OAuth scopes", () => {
    const html = renderToStaticMarkup(<PersonalWorkspacePage {...props} view="myConnections" />)
    expect(html).toContain("My OAuth grants")
    expect(html).toContain("Explicit confirmation in Gate")
    expect(html).toContain("within existing OAuth scopes")
    expect(html).toContain("without another client OAuth flow")
    expect(html).toContain("External identity provider")
    expect(html).not.toContain("Manage personal tokens")
  })
})
