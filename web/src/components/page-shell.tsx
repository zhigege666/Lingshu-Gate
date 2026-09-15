import type { ReactNode } from "react"
import { CloseOutlined, SearchOutlined } from "@ant-design/icons"
import { Button, Empty, Input, Steps, type StepsProps } from "antd"
import { cn } from "@/lib/utils"

type Tone = "default" | "success" | "warning" | "danger"

export function PageHeader({ title, description, eyebrow, actions, titleExtra, stats = [] }: {
  title: string
  description?: string
  eyebrow?: string
  actions?: ReactNode
  titleExtra?: ReactNode
  stats?: Array<{ label: string; value: ReactNode; tone?: Tone }>
}) {
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

export function PageToolbar({ query, onQueryChange, placeholder, resultCount, resultLabel, clearLabel, children, className }: {
  query?: string
  onQueryChange?: (value: string) => void
  placeholder?: string
  resultCount?: number
  resultLabel?: string
  clearLabel: string
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
        suffix={query ? <Button type="text" size="small" icon={<CloseOutlined />} onClick={() => onQueryChange("")} aria-label={clearLabel} /> : null}
      />}
      {resultCount !== undefined && <span className="page-result-count"><strong>{resultCount}</strong> {resultLabel || ""}</span>}
    </div>
    {children && <div className="page-toolbar-filters">{children}</div>}
  </div>
}

export function WorkflowSteps({ steps, ariaLabel }: { steps: Array<{ label: string; state?: "done" | "current" | "next" }>; ariaLabel: string }) {
  const items: StepsProps["items"] = steps.map(step => ({
    title: step.label,
    status: step.state === "done" ? "finish" : step.state === "current" ? "process" : "wait",
  }))
  return <div className="workflow-steps" aria-label={ariaLabel}><Steps size="small" items={items} /></div>
}

export function InlineEmpty({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <div className="inline-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<><strong>{title}</strong>{description && <p>{description}</p>}</>}>{action}</Empty></div>
}
