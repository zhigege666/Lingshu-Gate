import type { Locale } from "@/i18n"

const NAVIGATION_COPY = {
  "zh-CN": {
    labels: {
      overview: "总览",
      toolCatalog: "工具目录",
      toolTesting: "工具调试",
      healthChecks: "健康检查",
      users: "成员",
      myServers: "我的 MCP",
      myConnections: "我的连接",
      myInvocations: "我的调用",
      serviceOperations: "MCP 服务",
      serviceConfigurations: "服务配置",
      sharedCredentials: "共享服务凭据",
      projectDelivery: "项目交付",
      connectionInfrastructure: "连接基础设施",
      maintenance: "运行缓存",
      systemSettings: "系统设置",
      roles: "角色与权限",
      grants: "服务与工具授权",
      classifications: "工具审核",
      tokens: "Gate API 令牌",
      downstream: "我的服务凭据",
      audit: "调用审计",
    },
    sections: {
      overview: "服务",
      personal: "我的",
      access: "管理",
      manage: "服务管理",
      ops: "运行",
      tools: "工具",
    },
  },
  "en-US": {
    labels: {
      overview: "Overview",
      toolCatalog: "Tool catalog",
      toolTesting: "Tool testing",
      healthChecks: "Health checks",
      users: "Members",
      myServers: "My MCP",
      myConnections: "My connections",
      myInvocations: "My invocations",
      serviceOperations: "MCP services",
      serviceConfigurations: "Service configurations",
      sharedCredentials: "Shared service credentials",
      projectDelivery: "Project delivery",
      connectionInfrastructure: "Connection infrastructure",
      maintenance: "Runtime cache",
      systemSettings: "System settings",
      roles: "Roles & permissions",
      grants: "Service & tool access",
      classifications: "Tool review",
      tokens: "Gate API tokens",
      downstream: "My service credentials",
      audit: "Invocation Audit",
    },
    sections: {
      overview: "Services",
      personal: "Personal",
      access: "Administration",
      manage: "Management",
      ops: "Operations",
      tools: "Tools",
    },
  },
} as const

export type NavigationLabelKey = keyof (typeof NAVIGATION_COPY)["zh-CN"]["labels"]
export type NavigationSectionKey = keyof (typeof NAVIGATION_COPY)["zh-CN"]["sections"]

export function navigationCopy(locale: Locale) {
  return NAVIGATION_COPY[locale]
}
