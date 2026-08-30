import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { ShieldCheck, UserPlus } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { getInitialLocale, type Locale } from "@/i18n"

const AUTH_COPY = {
  "zh-CN": {
    loading: "加载登录状态...",
    loginTitle: "登录 Lingshu Gate",
    registerTitle: "创建 Lingshu Gate 账号",
    changeTitle: "修改临时密码",
    loginDesc: "统一管理 MCP 服务、工具授权与调用审计。",
    registerDesc: "提交注册后，由管理员审核并分配角色与 MCP 资源权限。",
    changeDesc: "默认账号 admin 使用临时密码。设置新密码后需要重新登录。",
    productEyebrow: "MCP ACCESS GOVERNANCE",
    productTitle: "让每一次工具调用都有明确边界",
    productDesc: "读写分类、用户授权、凭据范围与调用审计在同一控制面形成闭环。",
    classificationFeature: "规则建议辅助预判，人工发布决定最终权限",
    lifecycleFeature: "注册、审核、授权、调用与审计形成完整链路",
    displayName: "显示名称",
    username: "用户名",
    password: "密码",
    newPassword: "新密码",
    confirmPassword: "确认密码",
    passwordHint: "至少 8 位字符",
    loginSubmit: "登录",
    registerSubmit: "提交注册",
    changeSubmit: "保存新密码",
    registerLink: "还没有账号？注册",
    loginLink: "已有账号？返回登录",
    pendingNotice: "注册已提交，管理员审核通过后即可登录。",
    changeNotice: "密码已更新，请使用新密码重新登录。",
    mismatch: "两次输入的密码不一致",
  },
  "en-US": {
    loading: "Loading session...",
    loginTitle: "Sign in to Lingshu Gate",
    registerTitle: "Create a Lingshu Gate account",
    changeTitle: "Change temporary password",
    loginDesc: "Manage MCP services, tool grants, and invocation audits in one place.",
    registerDesc: "An administrator will review the account and assign roles and MCP access.",
    changeDesc: "The default admin account uses a temporary password. Set a new password and sign in again.",
    productEyebrow: "MCP ACCESS GOVERNANCE",
    productTitle: "Give every tool invocation a clear boundary",
    productDesc: "Tool classification, grants, credential scopes, and audits form one governance loop.",
    classificationFeature: "Rule suggestions support review; human publishing determines access",
    lifecycleFeature: "Registration, review, grants, invocation, and auditing stay connected",
    displayName: "Display name",
    username: "Username",
    password: "Password",
    newPassword: "New password",
    confirmPassword: "Confirm password",
    passwordHint: "At least 8 characters",
    loginSubmit: "Sign in",
    registerSubmit: "Submit registration",
    changeSubmit: "Save new password",
    registerLink: "Need an account? Register",
    loginLink: "Already registered? Sign in",
    pendingNotice: "Registration submitted. You can sign in after administrator approval.",
    changeNotice: "Password updated. Sign in again with the new password.",
    mismatch: "Passwords do not match",
  },
} satisfies Record<Locale, Record<string, string>>

export type AuthUser = {
  id: string
  username: string
  display_name: string
  role: string
  roles: string[]
  permissions: string[]
  status: string
  must_change_password: boolean
  auth_type: string
  token_id?: string | null
  scopes: string[]
}

type AuthMode = "loading" | "login" | "register" | "password" | "ready"

type AuthGateProps = {
  children: ReactNode
}

type AuthContextValue = {
  user: AuthUser
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error("useAuth must be used within AuthGate")
  return context
}

async function authRequest<T>(path: string, body?: Record<string, unknown>, method?: string): Promise<T> {
  const response = await fetch(path, {
    method: method || (body ? "POST" : "GET"),
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const text = await response.text()
  const data = text ? JSON.parse(text) : {}
  if (!response.ok) throw new Error(data?.detail || `${response.status} ${response.statusText}`)
  return data as T
}

export function AuthGate({ children }: AuthGateProps) {
  const c = AUTH_COPY[getInitialLocale()]
  const [mode, setMode] = useState<AuthMode>("loading")
  const [user, setUser] = useState<AuthUser | null>(null)
  const [displayName, setDisplayName] = useState("")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function loadMe() {
    try {
      const next = await authRequest<AuthUser>("/v1/auth/me")
      setUser(next)
      setMode(next.must_change_password ? "password" : "ready")
      setError(null)
    } catch (err) {
      setMode("login")
      setError(null)
    }
  }

  useEffect(() => { loadMe() }, [])

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const response = await authRequest<{ user: AuthUser }>("/v1/auth/login", { username, password })
      setUser(response.user)
      setMode(response.user.must_change_password ? "password" : "ready")
      setPassword("")
      setConfirmPassword("")
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function register() {
    if (password !== confirmPassword) {
      setError(c.mismatch)
      return
    }
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await authRequest("/v1/auth/register", { username, display_name: displayName, password })
      setNotice(c.pendingNotice)
      setMode("login")
      setPassword("")
      setConfirmPassword("")
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function changePassword() {
    if (password !== confirmPassword) {
      setError(c.mismatch)
      return
    }
    setBusy(true)
    setError(null)
    try {
      await authRequest("/v1/auth/password", { password })
      setUser(null)
      setPassword("")
      setConfirmPassword("")
      setNotice(c.changeNotice)
      setMode("login")
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function logout() {
    setBusy(true)
    try {
      await authRequest("/v1/auth/logout", {})
      setUser(null)
      setMode("login")
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  if (mode === "loading") {
    return <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">{c.loading}</div>
  }

  if (mode === "login" || mode === "register" || mode === "password") {
    const isRegister = mode === "register"
    const isPasswordChange = mode === "password"
    return (
      <div className="grid min-h-screen bg-background text-foreground lg:grid-cols-[minmax(360px,0.9fr)_minmax(460px,1.1fr)]">
        <section className="hidden flex-col justify-between border-r bg-primary p-10 text-primary-foreground lg:flex">
          <div className="flex items-center gap-3">
            <div className="flex size-11 items-center justify-center rounded-xl bg-white/95 shadow-sm"><img src="/console/lingshu-gate-icon.svg" alt="Lingshu Gate" className="size-7" /></div>
            <div><div className="font-semibold">Lingshu Gate</div><div className="text-xs text-primary-foreground/70">Access Governance Console</div></div>
          </div>
          <div className="max-w-xl">
            <div className="mb-4 text-xs font-semibold tracking-[0.2em] text-primary-foreground/70">{c.productEyebrow}</div>
            <h1 className="text-4xl font-semibold leading-tight tracking-tight">{c.productTitle}</h1>
            <p className="mt-5 max-w-lg text-base leading-7 text-primary-foreground/75">{c.productDesc}</p>
            <div className="mt-8 grid gap-3 text-sm text-primary-foreground/85">
              <div className="flex items-center gap-3"><ShieldCheck className="size-5" />{c.classificationFeature}</div>
              <div className="flex items-center gap-3"><UserPlus className="size-5" />{c.lifecycleFeature}</div>
            </div>
          </div>
          <div className="text-xs text-primary-foreground/60">Lingshu Gate · MCP Gateway</div>
        </section>
        <div className="flex items-center justify-center p-5 sm:p-8">
        <Card className="w-full max-w-md border-border/80 shadow-xl shadow-primary/5">
          <CardHeader>
            <div className="mb-3 flex items-center gap-3 lg:hidden">
              <div className="flex size-10 items-center justify-center rounded-xl border bg-background shadow-sm"><img src="/console/lingshu-gate-icon.svg" alt="Lingshu Gate" className="size-6" /></div>
              <div className="text-sm font-semibold">Lingshu Gate</div>
            </div>
            <CardTitle>{isRegister ? c.registerTitle : isPasswordChange ? c.changeTitle : c.loginTitle}</CardTitle>
            <CardDescription>{isRegister ? c.registerDesc : isPasswordChange ? c.changeDesc : c.loginDesc}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
            {notice && <Alert><AlertDescription>{notice}</AlertDescription></Alert>}
            {isRegister && <div className="flex flex-col gap-2"><Label htmlFor="auth-display-name">{c.displayName}</Label><Input id="auth-display-name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" /></div>}
            {!isPasswordChange && <div className="flex flex-col gap-2"><Label>{c.username}</Label><Input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></div>}
            <div className="flex flex-col gap-2"><Label>{isPasswordChange ? c.newPassword : c.password}</Label><Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />{mode !== "login" && <div className="text-xs text-muted-foreground">{c.passwordHint}</div>}</div>
            {(isRegister || isPasswordChange) && <div className="flex flex-col gap-2"><Label>{c.confirmPassword}</Label><Input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" /></div>}
            <Button className="w-full" onClick={isRegister ? register : isPasswordChange ? changePassword : submit} disabled={busy || (!isPasswordChange && !username) || password.length < (mode === "login" ? 1 : 8) || ((isRegister || isPasswordChange) && !confirmPassword)}>{isRegister ? c.registerSubmit : isPasswordChange ? c.changeSubmit : c.loginSubmit}</Button>
            {(mode === "login" || mode === "register") && <Button variant="ghost" className="w-full" onClick={() => { setMode(isRegister ? "login" : "register"); setError(null); setNotice(null) }}>{isRegister ? c.loginLink : c.registerLink}</Button>}
          </CardContent>
        </Card>
        </div>
      </div>
    )
  }

  if (!user) return null
  return <AuthContext.Provider value={{ user, logout }}>{children}</AuthContext.Provider>
}
