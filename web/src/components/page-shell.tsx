import type { ReactNode } from "react"
import { CloseOutlined, QuestionCircleOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons"
import { Button, Empty, Input, Steps, type StepsProps } from "antd"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

type Tone = "default" | "success" | "warning" | "danger"

export function PageHeader({ title, description, eyebrow, actions, titleExtra, stats = [], variant = "compact", toolbar, helpLabel, helpContent, closeLabel }: {
  title: string
  description?: string
  eyebrow?: string
  actions?: ReactNode
  titleExtra?: ReactNode
  stats?: Array<{ label: string; value: ReactNode; tone?: Tone }>
  variant?: "compact" | "detail"
  toolbar?: ReactNode
  helpLabel?: string
  helpContent?: ReactNode
  closeLabel?: string
}) {
  // 列表页复用全局导航标题；详情页保留资源名称，避免丢失当前操作对象。
  if (variant === "compact") return <header className="page-header page-header-compact" data-has-actions={Boolean(actions)}>
    <h1>{title}</h1>
    <div className="page-header-controls">
      {toolbar && <div className="page-header-toolbar">{toolbar}</div>}
      {stats.length > 0 && <div className="page-stats">{stats.map(stat => <PageStat key={stat.label} {...stat} />)}</div>}
      <div className="page-header-actions">
        {actions}
        {(description || helpContent) && <Dialog>
          <DialogTrigger asChild><Button type="text" icon={<QuestionCircleOutlined />} aria-label={helpLabel || title} title={helpLabel || title} /></DialogTrigger>
          <DialogContent closeLabel={closeLabel}>
            <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
            <DialogBody className="space-y-3 text-sm leading-6">
              <DialogDescription className="whitespace-pre-wrap break-words leading-6">{description}</DialogDescription>
              {helpContent}
            </DialogBody>
          </DialogContent>
        </Dialog>}
      </div>
    </div>
  </header>
  return <header className="page-header">
    <div className="page-header-main">
      <div className="min-w-0">
        {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
        <div className="page-title-line"><h1 title={title}>{title}</h1>{titleExtra}</div>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
    {stats.length > 0 && <div className="page-stats">{stats.map(stat => <PageStat key={stat.label} {...stat} />)}</div>}
  </header>
}

export function PageStat({ label, value, tone = "default" }: { label: string; value: ReactNode; tone?: Tone }) {
  return <div className={"page-stat page-stat-" + tone}><span>{label}</span><strong>{value}</strong></div>
}

export function PageToolbar({ query, onQueryChange, placeholder, resultCount, resultLabel, clearLabel, children, className, resetFilters }: {
  query?: string
  onQueryChange?: (value: string) => void
  placeholder?: string
  resultCount?: number
  resultLabel?: string
  clearLabel: string
  resetFilters?: { label: string; onReset: () => void; disabled?: boolean }
  children?: ReactNode
  className?: string
}) {
  return <div className={cn("page-toolbar", className)}>
    <div className="page-toolbar-search">
      {onQueryChange && <Input
        value={query || ""}
        onChange={event => onQueryChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        prefix={<SearchOutlined />}
        suffix={<span className="page-toolbar-clear-slot">{query && <Button type="text" size="small" icon={<CloseOutlined />} onClick={() => onQueryChange("")} aria-label={clearLabel} />}</span>}
      />}
      {resultCount !== undefined && <span className="page-result-count"><strong>{resultCount}</strong> {resultLabel || ""}</span>}
      {resetFilters && <Button className="page-toolbar-reset" aria-label={resetFilters.label} type="text" size="small" icon={<ReloadOutlined />} disabled={resetFilters.disabled} onClick={resetFilters.onReset}>{resetFilters.label}</Button>}
    </div>
    {children && <div className="page-toolbar-filters">{children}</div>}
  </div>
}

export function WorkflowSteps({ steps, ariaLabel, responsive = true, stacked = false, stateLabels }: { responsive?: boolean; stacked?: boolean; stateLabels?: Record<"done" | "current" | "next", string>; steps: Array<{ label: string; state?: "done" | "current" | "next"; icon?: ReactNode; statusLabel?: string; failed?: boolean }>; ariaLabel: string }) {
  if (stacked) return <ol className="workflow-steps workflow-steps-stacked" aria-label={ariaLabel}>{steps.map((step, index) => <li key={step.label} data-state={step.state || "next"} data-failed={step.failed || undefined} aria-current={step.state === "current" ? "step" : undefined}>
    <span className="workflow-step-symbol" aria-hidden="true">{step.icon || index + 1}</span>
    <strong>{step.label}</strong>
    <small>{step.statusLabel || stateLabels?.[step.state || "next"] || step.state || "next"}</small>
  </li>)}</ol>
  const items: StepsProps["items"] = steps.map(step => ({
    title: step.label,
    status: step.state === "done" ? "finish" : step.state === "current" ? "process" : "wait",
  }))
  return <div className="workflow-steps" aria-label={ariaLabel}><Steps size="small" responsive={responsive} items={items} /></div>
}

export function InlineEmpty({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <div className="inline-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<><strong>{title}</strong>{description && <p>{description}</p>}</>}>{action}</Empty></div>
}
