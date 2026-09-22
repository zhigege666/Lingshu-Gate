import { useEffect, useMemo, useRef, useState } from "react"
import { KeyRound, Plus, RefreshCcw } from "lucide-react"
import { api, type Credential, type CredentialSaveRequest } from "@/api/client"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { useConfirm } from "@/components/confirm-dialog"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Toaster, type ToastState } from "@/components/ui/toast"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import type { TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"

const emptyForm: CredentialSaveRequest = {
  name: "",
  value: "",
  description: "",
}

export function CredentialsPage({ t }: { t: TFunction }) {
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [editorOpen, setEditorOpen] = useState(false)
  const createTrigger = useRef<HTMLButtonElement>(null)
  const editorReturnFocus = useRef<HTMLButtonElement | null>(null)
  const [form, setForm] = useState<CredentialSaveRequest>({ ...emptyForm })
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [detail, setDetail] = useState<{ title: string; body: unknown } | null>(null)
  const [query, setQuery] = useState("")
  const { confirm, confirmDialog } = useConfirm(t)
  const filteredCredentials = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return credentials
    return credentials.filter((credential) => `${credential.id} ${credential.name} ${credential.description || ""}`.toLowerCase().includes(needle))
  }, [credentials, query])

  useEffect(() => { void load() }, [])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      setCredentials(await api.credentials())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function edit(credential: Credential, menuItem: HTMLButtonElement) {
    // 菜单项打开弹窗后会卸载，关闭时应回到仍在表格中的菜单按钮。
    const menuId = menuItem.closest('[role="menu"]')?.id
    editorReturnFocus.current = Array.from(document.querySelectorAll<HTMLButtonElement>('button[aria-controls]'))
      .find(button => button.getAttribute("aria-controls") === menuId) || createTrigger.current
    setError(null)
    setSelectedId(credential.id)
    setForm({ name: credential.name, value: "***", description: credential.description })
    setEditorOpen(true)
  }

  function createNew() {
    editorReturnFocus.current = createTrigger.current
    setError(null)
    setSelectedId("")
    setForm({ ...emptyForm })
    setEditorOpen(true)
  }

  async function save() {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const payload = { ...form, value: form.value || null }
      const credential = selectedId ? await api.updateCredential(selectedId, payload) : await api.createCredential(payload)
      setSelectedId(credential.id)
      setForm({ name: credential.name, value: "***", description: credential.description })
      setMessage(`${t("saved")}: ${credential.id}`)
      await load()
      setEditorOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: string) {
    if (!(await confirm({ title: t("confirmDeleteCredential"), description: id, destructive: true }))) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteCredential(id)
      setMessage(`${t("deleted")}: ${id}`)
      if (selectedId === id) {
        setSelectedId("")
        setForm({ ...emptyForm })
        setEditorOpen(false)
      }
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function copyReference(id: string) {
    const reference = credentialRef(id)
    try {
      await navigator.clipboard.writeText(reference)
      setMessage(`${t("copied")}: ${reference}`)
    } catch {
      setDetail({ title: `${t("copyRef")}: ${id}`, body: { reference, env_example: `API_KEY=${reference}` } })
    }
  }

  function showDetail(credential: Credential) {
    setDetail({ title: credential.id, body: { credential, reference: credentialRef(credential.id) } })
  }

  const toast: ToastState = editorOpen ? null : error ? { message: error, tone: "error" } : message ? { message, tone: "success" } : null
  const nameInvalid = form.name.trim() === ""
  const valueInvalid = !selectedId && (form.value || "").trim() === ""

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={t("secretsCenter")}
        title={t("credentials")}
        description={t("credentialsDesc")}
        helpLabel={t("pageHelp")}
        toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ID / ${t("name")}`} resultCount={filteredCredentials.length} resultLabel={t("credentials")} clearLabel={t("clearSearch")} />}
        actions={<><Button ref={createTrigger} onClick={createNew} disabled={busy}><Plus />{t("newCredential")}</Button><Button variant="outline" onClick={load} disabled={busy}><RefreshCcw />{t("refresh")}</Button></>}
      />
      <Dialog open={editorOpen} onOpenChange={(open) => { if (!busy) setEditorOpen(open) }}>
        <DialogContent onCloseAutoFocus={(event) => {
          event.preventDefault()
          const trigger = editorReturnFocus.current?.isConnected ? editorReturnFocus.current : createTrigger.current
          trigger?.focus()
        }}>
          <DialogHeader>
            <DialogTitle>{selectedId ? t("editCredential") : t("newCredential")}</DialogTitle>
            <DialogDescription>{t("credentialsDesc")}</DialogDescription>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-3">
            {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
            <div className="flex flex-col gap-2"><Label>{t("name")}</Label><Input value={form.name} aria-invalid={nameInvalid || undefined} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="SERVICE_PASSWORD" />{nameInvalid && <span className="text-xs text-destructive">{t("required")}</span>}</div>
            <div className="flex flex-col gap-2"><Label>{t("credentialValue")}</Label><Input type="password" value={form.value || ""} aria-invalid={valueInvalid || undefined} onChange={(event) => setForm((current) => ({ ...current, value: event.target.value }))} placeholder={selectedId ? "***" : "secret value"} />{valueInvalid && <span className="text-xs text-destructive">{t("required")}</span>}</div>
            <div className="flex flex-col gap-2"><Label>{t("description")}</Label><Textarea value={form.description || ""} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder="Password used by the example MCP server" /></div>
            <div className="rounded-md border bg-muted p-2 text-xs text-muted-foreground">{t("credentialRefHint")}</div>
            <div className="flex justify-end gap-2 border-t pt-3"><Button variant="outline" onClick={() => setEditorOpen(false)} disabled={busy}>{t("cancel")}</Button><Button onClick={save} disabled={busy || nameInvalid || valueInvalid}><KeyRound />{t("save")}</Button></div>
          </DialogBody>
        </DialogContent>
      </Dialog>

        <Card>
          <CardContent className="overflow-x-auto p-3 md:p-4">
            <Table>
              <TableHeader><TableRow><TableHead>{t("id")}</TableHead><TableHead>{t("name")}</TableHead><TableHead>{t("description")}</TableHead><TableHead>{t("updatedAt")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {filteredCredentials.length === 0 ? <TableEmptyRow colSpan={5} title={t("noData")} /> : filteredCredentials.map((credential) => <TableRow key={credential.id} className={selectedId === credential.id ? "cursor-pointer bg-accent/50" : "cursor-pointer"} onClick={() => showDetail(credential)}>
                  <TableCell><code>{credential.id}</code><div className="text-xs text-muted-foreground">{credential.value_masked}</div></TableCell>
                  <TableCell>{credential.name}</TableCell>
                  <TableCell>{credential.description || "-"}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs">{formatDateTime(credential.updated_at)}</TableCell>
                  <TableCell onClick={(event) => event.stopPropagation()}><ActionMenu label={t("actions")}><ActionMenuItem disabled={busy} onClick={(event) => edit(credential, event.currentTarget)}>{t("edit")}</ActionMenuItem><ActionMenuItem onClick={() => void copyReference(credential.id)}>{t("copyRef")}</ActionMenuItem><ActionMenuItem onClick={() => showDetail(credential)}>{t("detail")}</ActionMenuItem><ActionMenuItem destructive disabled={busy} onClick={() => void remove(credential.id)}>{t("delete")}</ActionMenuItem></ActionMenu></TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

      <Dialog open={detail !== null} onOpenChange={(open) => { if (!open) setDetail(null) }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>{detail?.title || ""}</DialogTitle><DialogDescription>{t("credentialResultDesc")}</DialogDescription></DialogHeader>
          <DialogBody><JsonPanel data={detail?.body} maxHeight="max-h-[60vh]" /></DialogBody>
        </DialogContent>
      </Dialog>
      {confirmDialog}
      <Toaster toast={toast} onClose={() => { setMessage(null); setError(null) }} />
    </div>
  )
}

function credentialRef(id: string) {
  return `\${credential:${id}}`
}
