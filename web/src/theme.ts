export type ThemeMode = "light" | "dark"

export function getInitialTheme(): ThemeMode {
  const stored = window.localStorage.getItem("lingshu-gate-console-theme")
  if (stored === "light" || stored === "dark") return stored
  return "light"
}

export function applyTheme(theme: ThemeMode) {
  document.documentElement.classList.toggle("dark", theme === "dark")
  document.documentElement.style.colorScheme = theme
  window.localStorage.setItem("lingshu-gate-console-theme", theme)
}
