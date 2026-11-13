// Static source-contract checks only. Matching source text does not validate
// browser interactions, visual quality, or accessibility.
import { readFile, readdir } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"
import { validateI18nMessages } from "./i18n-contract.mjs"

const webRoot = dirname(dirname(fileURLToPath(import.meta.url)))
const pageRoot = join(webRoot, "src", "pages")
const pageNames = [
  "dashboard-page.tsx",
  "configs-page.tsx",
  "servers-page.tsx",
  "builds-page.tsx",
  "credentials-page.tsx",
  "diagnostics-page.tsx",
  "tools-page.tsx",
  "invoke-page.tsx",
  "logs-events-page.tsx",
  "runtime-cache-page.tsx",
  "uploads-page.tsx",
  "system-settings-page.tsx",
  "tool-classifications-page.tsx",
  "access-users-page.tsx",
  "access-roles-page.tsx",
  "access-grants-page.tsx",
  "personal-tokens-page.tsx",
  "downstream-credentials-page.tsx",
  "invocation-audit-page.tsx",
]
const searchablePages = new Set([
  "configs-page.tsx",
  "servers-page.tsx",
  "credentials-page.tsx",
  "diagnostics-page.tsx",
  "tools-page.tsx",
  "runtime-cache-page.tsx",
  "uploads-page.tsx",
  "tool-classifications-page.tsx",
  "access-users-page.tsx",
  "access-grants-page.tsx",
  "invocation-audit-page.tsx",
])
const workflowPages = new Set([
  "builds-page.tsx",
  "uploads-page.tsx",
])

function assertContract(condition, message) {
  if (!condition) throw new Error(`静态 UI 契约失败：${message}`)
}

for (const pageName of pageNames) {
  const source = await readFile(join(pageRoot, pageName), "utf8")
  if (pageName === "personal-tokens-page.tsx") {
    assertContract(source.includes("MyAuthorizationsPage"), `${pageName} 必须复用统一授权页面`)
  } else {
    assertContract(source.includes("PageHeader"), `${pageName} 缺少统一页面标题`)
  }
  // Help is contextual, not a mandatory extra button on every page.
  if (source.includes("FormDialog")) {
    assertContract(source.includes('closeLabel={t("close")}'), `${pageName} 缺少多语言关闭按钮`)
  }
  assertContract(!/eyebrow="[^"]+"/.test(source), `${pageName} 的页面分类未经过多语言`)
  if (searchablePages.has(pageName)) {
    assertContract(source.includes("PageToolbar"), `${pageName} 缺少搜索或筛选工具栏`)
    assertContract(source.includes('clearLabel={t("clearSearch")}'), `${pageName} 的清除搜索按钮未经过多语言`)
  }
  if (workflowPages.has(pageName)) {
    assertContract(source.includes("WorkflowSteps"), `${pageName} 缺少阶段式工作流`)
    assertContract(source.includes('ariaLabel={t("workflowProgress")}'), `${pageName} 的工作流标签未经过多语言`)
  }
}

const i18nSource = await readFile(join(webRoot, "src", "i18n.ts"), "utf8")
try {
  validateI18nMessages(i18nSource)
} catch (error) {
  assertContract(false, error instanceof Error ? error.message : "无法解析语言词条")
}

const actionMenuSource = await readFile(join(webRoot, "src", "components", "action-menu.tsx"), "utf8")
assertContract(actionMenuSource.includes("createPortal"), "操作菜单必须通过 Portal 渲染，避免被表格滚动容器裁剪")

const classificationSource = await readFile(join(pageRoot, "tool-classifications-page.tsx"), "utf8")
const policySource = await readFile(join(webRoot, "src", "features", "tool-policy.ts"), "utf8")
assertContract(classificationSource.includes("saveToolPolicyBatch"), "工具权限页必须通过统一批量保存处理部分成功")
assertContract(policySource.includes("expected_fingerprint: item.fingerprint"), "工具权限保存缺少并发版本保护")
assertContract(policySource.includes("item.required_access"), "工具权限展示必须使用后端有效策略")
assertContract(!/api\.(analyze|confirm|publish)ToolClassifications/.test(classificationSource), "工具权限页不得恢复日常审核发布流程")

// Enforce shared spacing without conflating source checks with browser QA.
const sourceRoot = join(webRoot, "src")
const cssFiles = (await readdir(sourceRoot, { recursive: true })).filter(file => file.endsWith(".css") && file !== "index.css")
for (const file of cssFiles) {
  const source = (await readFile(join(sourceRoot, file), "utf8")).replace(/\/\*[\s\S]*?\*\//g, "")
  const declarations = source.matchAll(/\b(?:gap|row-gap|column-gap|padding(?:-[\w-]+)?|margin(?:-[\w-]+)?)\s*:\s*([^;{}]+)/g)
  for (const declaration of declarations) {
    const rawLengths = [...declaration[1].matchAll(/(?<![\w.-])(-?(?:\d*\.)?\d+)(px|rem)\b/g)]
    const unscaled = rawLengths.some(([, number, unit]) => !(unit === "px" && Math.abs(Number(number)) <= 1))
    assertContract(!unscaled, file + " 的 " + declaration[0] + " 必须使用 index.css 中的间距变量")
  }
}

console.log(`静态 UI 契约通过：${pageNames.length} 个页面，${searchablePages.size} 个可搜索页面，${workflowPages.size} 个阶段式工作流，${cssFiles.length} 个样式文件使用统一间距。仅验证源码约定；未执行浏览器交互、视觉或可访问性验收。`)
