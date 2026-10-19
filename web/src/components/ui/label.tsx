import * as React from "react"
import { cn } from "@/lib/utils"
import { FieldHelp, fieldLabelText } from "@/components/field-help"

export interface LabelProps extends React.LabelHTMLAttributes<HTMLLabelElement> {
  help?: React.ReactNode
  helpLabel?: string
  helpId?: string
  zh?: boolean
}

export function Label({ className, help, helpLabel, helpId, zh, ...props }: LabelProps) {
  if (help != null) return <span className={cn("field-label", className)}>
    <label className="field-label-text text-sm font-medium leading-none text-foreground peer-disabled:cursor-not-allowed peer-disabled:opacity-70" {...props} />
    <FieldHelp label={helpLabel ?? fieldLabelText(props.children)} zh={zh} id={helpId}>{help}</FieldHelp>
  </span>
  return <label className={cn("text-sm font-medium leading-none text-foreground peer-disabled:cursor-not-allowed peer-disabled:opacity-70", className)} {...props} />
}
