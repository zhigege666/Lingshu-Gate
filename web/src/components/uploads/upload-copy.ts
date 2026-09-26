import type { TFunction } from "@/i18n"

const zh = {
  projectRootHint: "相对上传目录；. 表示项目根目录。",
  records: "上传记录", loading: "正在加载上传记录…", empty: "还没有上传记录。选择 ZIP 文件并上传分析。",
  noMatches: "没有匹配的上传记录，请调整搜索条件。", choose: "选择一条上传记录，查看分析或创建构建。",
  runtimeConfig: "运行配置", transport: "传输", editConfig: "编辑配置", analysis: "分析", raw: "原始响应", latestAction: "最近操作",
  saveHint: "保存为新的 MCP 配置，不应用或启动服务。", discard: "放弃未保存的配置修改？",
  discardHint: "关闭后将丢弃本次编辑；上传记录和已保存的配置不受影响。", keepEditing: "继续编辑", discardAction: "放弃修改",
  upload: "上传分析", draft: "生成配置草稿", save: "保存配置", build: "创建构建", deploy: "部署构建", delete: "删除上传",
  saved: "配置已保存，可到 MCP 配置页独立应用。", loadingFailed: "上传记录加载失败", removed: "此上传记录已不在刷新后的列表中；当前内容保留到关闭。",
  install: "按检测结果安装依赖", buildPlan: "构建选项", buildHint: "Gate 使用项目文件生成安装与构建步骤；服务启动仍使用 Manifest 配置。",
  liveConnection: "日志连接", connected: "已连接", disconnected: "未连接", selectBuild: "先从构建记录选择一个构建，再查看日志。",
  selectProject: "选择上传项目后运行预检或创建构建。", noProjects: "还没有可构建的项目。先上传并分析 ZIP 文件。",
  uploadProject: "上传项目", listFailed: "记录加载失败", refreshing: "正在刷新记录…",
} as const
const en: Record<keyof typeof zh, string> = {
  projectRootHint: "Relative to the upload directory; . means the project root.",
  records: "Upload history", loading: "Loading uploads…", empty: "No uploads yet. Choose a ZIP file to upload and analyze.",
  noMatches: "No matching uploads. Adjust the search.", choose: "Select an upload to inspect its analysis or create a build.",
  runtimeConfig: "Runtime configuration", transport: "Transport", editConfig: "Edit configuration", analysis: "Analysis", raw: "Raw response", latestAction: "Latest action",
  saveHint: "Save as a new MCP configuration without applying or starting the service.", discard: "Discard unsaved configuration changes?",
  discardHint: "Closing discards this edit. The upload and saved configurations are unchanged.", keepEditing: "Keep editing", discardAction: "Discard changes",
  upload: "Upload and analyze", draft: "Draft configuration", save: "Save configuration", build: "Create build", deploy: "Deploy build", delete: "Delete upload",
  saved: "Configuration saved. Apply it separately on the MCP configurations page.", loadingFailed: "Could not load uploads", removed: "This upload is no longer in the refreshed list. Its current content is retained until you close it.",
  install: "Install dependencies using detected settings", buildPlan: "Build options", buildHint: "Gate derives install and build steps from project files. Service startup still uses the Manifest configuration.",
  liveConnection: "Log connection", connected: "Connected", disconnected: "Disconnected", selectBuild: "Select a build from build history to view its logs.",
  selectProject: "Select an uploaded project to run preflight or create a build.", noProjects: "No projects are available to build. Upload and analyze a ZIP file first.",
  uploadProject: "Upload project", listFailed: "Could not load records", refreshing: "Refreshing records…",
}

export function uploadCopy(t: TFunction) { return t("uploads") === "项目上传" ? zh : en }
