import { Alert, Button } from "antd"
import type { ValidationIssue } from "@/lib/validation"

/** Persistent summary. Consumers own focus/reveal and revision filtering. */
export function ValidationErrors({ issues, title, onSelect, id }: { issues: ValidationIssue[]; title: string; onSelect: (issue: ValidationIssue) => void; id?:string }) {
  if (!issues.length) return null
  return <Alert id={id} type={issues.some(issue=>issue.severity === "error") ? "error" : "warning"} showIcon role="alert" title={title} description={
    <ul style={{ margin: "4px 0 0", paddingInlineStart: 18 }}>
      {issues.map((issue, index) => <li key={`${issue.path}:${issue.code}:${index}`}>
        <Button type="link" size="small" style={{ height: "auto", padding: 0, whiteSpace: "normal", textAlign: "start" }} onClick={() => onSelect(issue)}>
          {issue.path && <><code>{issue.path}</code>: </>}{issue.message}
        </Button>
      </li>)}
    </ul>
  } />
}
