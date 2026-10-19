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

/** CSS owns dimensions; fallbacks support rendering without styles. */
function readConsoleDimensions() {
  const styles = typeof document === "undefined" ? null : getComputedStyle(document.documentElement)
  const value = (name: string, fallback: number) => {
    const parsed = Number.parseFloat(styles?.getPropertyValue(name) ?? "")
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
  }
  return {
    controlHeight: value("--control-height", 36),
    controlHeightSM: value("--control-height-sm", 32),
    controlHeightLG: value("--control-height-lg", 40),
    borderRadius: value("--radius-control", 8),
    panelRadius: value("--radius-panel", 12),
    dialogRadius: value("--radius-dialog", 16),
    fieldGap: value("--field-gap", 16),
    panelPadding: value("--panel-padding", 24),
    cellInline: value("--table-cell-padding-inline", 16),
    cellBlock: value("--table-cell-padding-block", 12),
    cellCompact: value("--table-cell-padding-compact", 8),
  }
}

export function ConsoleDesignProvider({ children, initialLocale }: { children: ReactNode; initialLocale?: Locale }) {
  const [mode, setMode] = useState<ThemeMode>(getInitialTheme)
  const [locale, setLocaleState] = useState<Locale>(() => initialLocale ?? getInitialLocale())
  useEffect(() => { applyTheme(mode) }, [mode])
  useEffect(() => { document.documentElement.lang = locale }, [locale])
  const [dimensions, setDimensions] = useState(readConsoleDimensions)
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return
    const compact = window.matchMedia("(max-width: 720px)")
    const syncDimensions = () => setDimensions(readConsoleDimensions())
    compact.addEventListener("change", syncDimensions)
    return () => compact.removeEventListener("change", syncDimensions)
  }, [])
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
      fontSizeSM: 13,
      borderRadius: dimensions.borderRadius,
      motionDurationFast: "0.12s",
      motionDurationMid: "0.18s",
      motionDurationSlow: "0.24s",
      controlHeight: dimensions.controlHeight,
      controlHeightSM: dimensions.controlHeightSM,
      controlHeightLG: dimensions.controlHeightLG,
      boxShadow: "0 10px 32px rgb(0 0 0 / 16%)",
    },
    components: {
      Button: { primaryShadow: "none", defaultShadow: "none", colorPrimary: "#1d62d0", colorPrimaryHover: "#1755b7", colorPrimaryActive: "#124699", paddingInline: 16, paddingInlineSM: 12 },
      Tabs: { horizontalItemGutter: 24, titleFontSize: 14 },
      Table: { cellPaddingBlock: dimensions.cellBlock, cellPaddingInline: dimensions.cellInline, cellPaddingBlockMD: dimensions.cellCompact, cellPaddingInlineMD: dimensions.cellInline, cellPaddingBlockSM: dimensions.cellCompact, cellPaddingInlineSM: dimensions.cellInline, headerBorderRadius: 0 },
      Card: { bodyPadding: dimensions.panelPadding, headerPadding: dimensions.panelPadding, borderRadiusLG: dimensions.panelRadius, headerFontSize: 16 },
      Form: { itemMarginBottom: dimensions.fieldGap },
      Modal: { borderRadiusLG: dimensions.dialogRadius },
      Menu: { itemBorderRadius: dimensions.borderRadius, itemHeight: 40 },
    },
  }), [mode, dimensions])

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
