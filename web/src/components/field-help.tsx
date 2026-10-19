import { Children, isValidElement, useEffect, useId, useRef, useState, type MouseEvent, type ReactNode } from "react"
import { Popover } from "antd"
import { CircleHelp } from "lucide-react"
import { cn } from "@/lib/utils"

export function fieldLabelText(value: ReactNode): string {
  return Children.toArray(value).map(child => {
    if (typeof child === "string" || typeof child === "number") return String(child)
    if (isValidElement<{ children?: ReactNode }>(child)) return fieldLabelText(child.props.children)
    return ""
  }).join("")
}

/** Supplementary field text. Errors, live state and confirmation actions stay beside the control. */
export function FieldHelp({ label, children, zh, inline = false, id }: {
  label: string; children: ReactNode; zh?: boolean; inline?: boolean; id?: string
}) {
  const [open, setOpen] = useState(false)
  const generatedId = useId()
  const popupId = `${generatedId}-field-help`
  const trigger = useRef<HTMLElement | null>(null)
  const chinese = zh ?? /[\u3400-\u9fff]/u.test(label + fieldLabelText(children))
  const accessibleLabel = chinese ? `${label}说明` : `${label} help`

  useEffect(() => {
    if (!open) return
    // Capture at window before the parent Dialog's document-level Escape handler.
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      if (trigger.current?.isConnected) trigger.current.focus({ preventScroll: true })
    }
    window.addEventListener("keydown", closeOnEscape, true)
    return () => window.removeEventListener("keydown", closeOnEscape, true)
  }, [open])

  const triggerProps = {
    className: "field-help-trigger",
    "data-field-help-trigger": label,
    "aria-label": accessibleLabel,
    "aria-expanded": open,
    "aria-controls": open ? popupId : undefined,
    onClick: (event: MouseEvent<HTMLElement>) => {
      // A help icon inside an AntD/legacy label must not toggle its input or radio.
      event.preventDefault()
      event.stopPropagation()
    },
  }
  const icon = <CircleHelp aria-hidden="true" focusable="false" />
  return <>
    {id && <span id={id} hidden>{fieldLabelText(children)}</span>}
    <Popover trigger="click" open={open} onOpenChange={setOpen} destroyOnHidden
      placement="bottom" autoAdjustOverflow classNames={{ root: "field-help-popup" }}
      getPopupContainer={node => node.closest<HTMLElement>(".gate-dialog, .ant-modal-content") ?? document.body}
      title={label}
      content={<div id={popupId} className="field-help-content" data-field-help-content>{children}</div>}
    >
      {inline ? <span {...triggerProps} ref={node => { trigger.current = node }} role="button" tabIndex={0}
        onKeyDown={event => {
          if (event.key !== "Enter" && event.key !== " ") return
          event.preventDefault()
          event.stopPropagation()
          if (!event.repeat) event.currentTarget.click()
        }}
      >{icon}</span> : <button {...triggerProps} ref={node => { trigger.current = node }} type="button">{icon}</button>}
    </Popover>
  </>
}

/** Label content for AntD Form.Item and legacy labels; never nests another native label/button. */
export function FieldLabel({ label, help, zh, className, helpId }: {
  label: string; help?: ReactNode; zh?: boolean; className?: string; helpId?: string
}) {
  return <span className={cn("field-label", className)}><span className="field-label-text">{label}</span>
    {help != null && <FieldHelp label={label} zh={zh} inline id={helpId}>{help}</FieldHelp>}
  </span>
}
