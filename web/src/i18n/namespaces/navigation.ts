import type { Locale } from "@/i18n"

const NAVIGATION_COPY = {
  "zh-CN": {
    labels: {
      users: "用户管理",
      roles: "角色与权限类型",
      grants: "资源授权",
      classifications: "工具读写分类",
      tokens: "我的 API Token",
      downstream: "我的下游凭据",
      audit: "调用审计",
    },
    sections: {
      overview: "概览",
      access: "安全与访问",
      manage: "配置管理",
      ops: "运维观测",
      tools: "工具调用",
    },
  },
  "en-US": {
    labels: {
      users: "Users",
      roles: "Roles & Permission Types",
      grants: "Resource Grants",
      classifications: "Tool Classification",
      tokens: "My API Tokens",
      downstream: "My Downstream Credentials",
      audit: "Invocation Audit",
    },
    sections: {
      overview: "Overview",
      access: "Security & Access",
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
