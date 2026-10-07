import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { ActionMenu, ActionMenuItem } from "./action-menu"

describe("常驻操作按钮", () => {
  it("无需打开菜单即可看到操作，并使用普通按钮语义", () => {
    const html = renderToStaticMarkup(<ActionMenu inline label="操作">
      <ActionMenuItem>编辑</ActionMenuItem>
      <ActionMenuItem destructive disabled>删除</ActionMenuItem>
    </ActionMenu>)
    expect(html).toContain('role="group" aria-label="操作"')
    expect(html).toContain(">编辑</button>")
    expect(html).toContain(">删除</button>")
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>删除<\/button>/)
    expect(html).toContain("text-destructive")
    expect(html).not.toContain('role="menuitem"')
    expect(html).not.toContain('aria-haspopup="menu"')
  })
})
