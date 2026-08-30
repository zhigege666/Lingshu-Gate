import { useEffect, useMemo, useState } from "react"
import { KeyRound, Plus, RefreshCcw } from "lucide-react"
import { api, type Credential, type CredentialSaveRequest } from "@/api/client"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { useConfirm } from "@/components/confirm-dialog"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Toaster, type ToastState } from "@/components/ui/toast"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
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

  function edit(credential: Credential) {
    setSelectedId(credential.id)
    setForm({ name: credential.name, value: "***", description: credential.description })
  }

  function createNew() {
    setSelectedId("")
    setForm({ ...emptyForm })
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
      if (selectedId === id) createNew()
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

  const toast: ToastState = error ? { message: error, tone: "error" } : message ? { message, tone: "success" } : null
  const nameInvalid = form.name.trim() === ""
  const valueInvalid = !selectedId && (form.value || "").trim() === ""

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={t("secretsCenter")}
        title={t("credentials")}
        description={t("credentialsDesc")}
        stats={[{ label: t("total"), value: credentials.length }, { label: t("status"), value: selectedId || t("waiting") }]}
        actions={<><Button onClick={createNew} disabled={busy}><Plus />{t("newCredential")}</Button><Button variant="outline" onClick={load} disabled={busy}><RefreshCcw />{t("refresh")}</Button></>}
      />
      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card className="xl:order-2">
          <CardHeader>
            <CardTitle>{selectedId ? t("editCredential") : t("newCredential")}</CardTitle>
            <CardDescription>{t("credentialsDesc")}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-col gap-2"><Label>{t("name")}</Label><Input value={form.name} aria-invalid={nameInvalid || undefined} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="SERVICE_PASSWORD" />{nameInvalid && <span className="text-xs text-destructive">{t("required")}</span>}</div>
            <div className="flex flex-col gap-2"><Label>{t("credentialValue")}</Label><Input type="password" value={form.value || ""} aria-invalid={valueInvalid || undefined} onChange={(event) => setForm((current) => ({ ...current, value: event.target.value }))} placeholder={selectedId ? "***" : "secret value"} />{valueInvalid && <span className="text-xs text-destructive">{t("required")}</span>}</div>
            <div className="flex flex-col gap-2"><Label>{t("description")}</Label><Textarea value={form.description || ""} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder="Password used by the example MCP server" /></div>
            <div className="rounded-md border bg-muted p-2 text-xs text-muted-foreground">{t("credentialRefHint")}</div>
            <div className="sticky bottom-0 flex flex-wrap gap-2 border-t bg-card/95 pt-3 backdrop-blur"><Button onClick={save} disabled={busy || !form.name || (!selectedId && !form.value)}><KeyRound />{t("save")}</Button><Button variant="secondary" onClick={createNew} disabled={busy}>{t("cancel")}</Button></div>
          </CardContent>
        </Card>

        <Card className="xl:order-1">
          <CardHeader><CardTitle>{t("credentials")}</CardTitle><CardDescription>{t("credentialsListDesc")}</CardDescription></CardHeader>
          <CardContent className="flex flex-col gap-3">
            <PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ID / ${t("name")}`} resultCount={filteredCredentials.length} resultLabel={t("credentials")} clearLabel={t("clearSearch")} />
            <Table>
              <TableHeader><TableRow><TableHead>{t("id")}</TableHead><TableHead>{t("name")}</TableHead><TableHead>{t("description")}</TableHead><TableHead>{t("updatedAt")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {filteredCredentials.length === 0 ? <TableEmptyRow colSpan={5} title={t("noData")} /> : filteredCredentials.map((credential) => <TableRow key={credential.id} className={selectedId === credential.id ? "cursor-pointer bg-accent/50" : "cursor-pointer"} onClick={() => showDetail(credential)}>
                  <TableCell><code>{credential.id}</code><div className="text-xs text-muted-foreground">{credential.value_masked}</div></TableCell>
                  <TableCell>{credential.name}</TableCell>
                  <TableCell>{credential.description || "-"}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs">{formatDateTime(credential.updated_at)}</TableCell>
                  <TableCell onClick={(event) => event.stopPropagation()}><ActionMenu label={t("actions")}><ActionMenuItem onClick={() => edit(credential)}>{t("edit")}</ActionMenuItem><ActionMenuItem onClick={() => void copyReference(credential.id)}>{t("copyRef")}</ActionMenuItem><ActionMenuItem onClick={() => showDetail(credential)}>{t("detail")}</ActionMenuItem><ActionMenuItem destructive disabled={busy} onClick={() => void remove(credential.id)}>{t("delete")}</ActionMenuItem></ActionMenu></TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

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
