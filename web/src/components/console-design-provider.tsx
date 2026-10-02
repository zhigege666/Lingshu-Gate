import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import { ConfigProvider, theme as antTheme, type ThemeConfig } from "antd"
import zhCN from "antd/locale/zh_CN"
import enUS from "antd/locale/en_US"
import { getInitialLocale, saveLocale, type Locale } from "@/i18n"
import { applyTheme, getInitialTheme, type ThemeMode } from "@/theme"

type ConsoleDesign = {
  theme: ThemeMode
  setTheme: (value: ThemeMode) => void
  locale: Locale
  setLocale: (value: Locale) => void
}

const ConsoleDesignContext = createContext<ConsoleDesign | null>(null)

export function ConsoleDesignProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(getInitialTheme)
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale)
  useEffect(() => { applyTheme(mode) }, [mode])
  useEffect(() => { document.documentElement.lang = locale }, [locale])
  const theme = useMemo<ThemeConfig>(() => ({
    algorithm: mode === "dark" ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
    token: {
      colorPrimary: mode === "dark" ? "#3b82f6" : "#1d62d0",
      colorInfo: mode === "dark" ? "#3b82f6" : "#1d62d0",
      colorSuccess: mode === "dark" ? "#4ade80" : "#15803d",
      colorWarning: mode === "dark" ? "#fbbf24" : "#a16207",
      colorError: mode === "dark" ? "#fda4af" : "#b42318",
      colorBgBase: mode === "dark" ? "#0d121a" : "#ffffff",
      colorBgContainer: mode === "dark" ? "#131a24" : "#ffffff",
      colorBgElevated: mode === "dark" ? "#1a2330" : "#ffffff",
      // Match --input and --border in index.css for AntD and native controls.
      colorBorder: mode === "dark" ? "hsl(215, 20%, 49%)" : "hsl(216, 16%, 54%)",
      colorBorderSecondary: mode === "dark" ? "hsl(216, 24%, 33%)" : "hsl(216, 22%, 86%)",
      colorSplit: mode === "dark" ? "hsl(216, 24%, 33%)" : "hsl(216, 22%, 86%)",
      colorText: mode === "dark" ? "#e6edf7" : "#1b273b",
      colorTextSecondary: mode === "dark" ? "#9daec4" : "#64748b",
      fontFamily: '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Noto Sans SC", system-ui, sans-serif',
      fontSize: 14,
      borderRadius: 8,
      motionDurationFast: "0.12s",
      motionDurationMid: "0.18s",
      motionDurationSlow: "0.24s",
      controlHeight: 36,
      controlHeightSM: 30,
      boxShadow: "0 10px 32px rgb(0 0 0 / 16%)",
    },
    components: {
      Button: { primaryShadow: "none", defaultShadow: "none", colorPrimary: "#246ddd", colorPrimaryHover: "#236fe0", colorPrimaryActive: "#165fc7" },
      Tabs: { horizontalItemGutter: 28, titleFontSize: 14 },
      Table: { cellPaddingBlock: 12, cellPaddingInline: 14, headerBorderRadius: 0 },
      Menu: { itemBorderRadius: 5, itemHeight: 38 },
    },
  }), [mode])

  function setLocale(value: Locale) { setLocaleState(value); saveLocale(value) }
  return <ConsoleDesignContext.Provider value={{ theme: mode, setTheme: setMode, locale, setLocale }}>
    <ConfigProvider locale={locale === "zh-CN" ? zhCN : enUS} theme={theme} button={{ autoInsertSpace: false }}>
      {children}
    </ConfigProvider>
  </ConsoleDesignContext.Provider>
}

export function useConsoleDesign() {
  const context = useContext(ConsoleDesignContext)
  if (!context) throw new Error("ConsoleDesignProvider is required")
  return context
}
