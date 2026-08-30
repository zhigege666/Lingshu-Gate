import { readFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

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
  "tool-classifications-page.tsx",
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
])
const workflowPages = new Set([
  "builds-page.tsx",
  "invoke-page.tsx",
  "uploads-page.tsx",
])

function assertContract(condition, message) {
  if (!condition) throw new Error(`UX 契约失败：${message}`)
}

for (const pageName of pageNames) {
  const source = await readFile(join(pageRoot, pageName), "utf8")
  assertContract(source.includes("PageHeader"), `${pageName} 未接入 PageHeader`)
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
const zhStart = i18nSource.indexOf('"zh-CN": {')
const enStart = i18nSource.indexOf('"en-US": {', zhStart)
const objectEnd = i18nSource.indexOf("\n  }\n}", enStart)
const readKeys = (source) => new Set(Array.from(source.matchAll(/^\s{4}([A-Za-z0-9_]+):/gm), (match) => match[1]))
const zhKeys = readKeys(i18nSource.slice(zhStart, enStart))
const enKeys = readKeys(i18nSource.slice(enStart, objectEnd))
assertContract(zhKeys.size === enKeys.size, `中英文词条数量不一致：${zhKeys.size}/${enKeys.size}`)
for (const key of zhKeys) assertContract(enKeys.has(key), `英文缺少词条 ${key}`)

const actionMenuSource = await readFile(join(webRoot, "src", "components", "action-menu.tsx"), "utf8")
assertContract(actionMenuSource.includes("createPortal"), "操作菜单必须通过 Portal 渲染，避免被表格滚动容器裁剪")

const classificationSource = await readFile(join(pageRoot, "tool-classifications-page.tsx"), "utf8")
const batchSetIndex = classificationSource.indexOf(">{c.batchClassify}")
const batchConfirmIndex = classificationSource.indexOf(">{c.confirmSelected}")
const publishIndex = classificationSource.indexOf(">{c.publishSelected}")
assertContract(classificationSource.includes("api.confirmToolClassifications"), "工具分类页缺少批量确认 API 调用")
assertContract(classificationSource.includes("expected_fingerprint: item.fingerprint"), "批量确认缺少 Tool fingerprint 并发保护")
assertContract(classificationSource.includes("const CONFIRM_BATCH_SIZE = 500"), "工具分类页缺少与后端一致的批量确认上限")
assertContract(classificationSource.includes("index += CONFIRM_BATCH_SIZE"), "工具分类页超过单批上限时必须自动拆批")
assertContract(classificationSource.includes("未处理项仍保持选择"), "批量确认失败后缺少刷新与选择恢复反馈")
assertContract(batchSetIndex >= 0 && batchSetIndex < batchConfirmIndex && batchConfirmIndex < publishIndex, "工具分类操作顺序必须是批量设置、批量确认、发布所选")
assertContract(classificationSource.includes("c.step4"), "工具分类页缺少独立的发布生效阶段")
assertContract(classificationSource.includes("labels.confirmedPending"), "工具分类页缺少已确认待发布状态")
assertContract(classificationSource.includes("labels.needsConfirmation"), "工具分类页缺少待确认状态")

console.log(`UX 契约通过：${pageNames.length} 个页面，${searchablePages.size} 个可搜索页面，${workflowPages.size} 个阶段式工作流。`)
