import * as React from "react"
import { cn } from "@/lib/utils"

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, ...props }, ref) => {
  return (
    <input
      className={cn(
        "gate-input flex h-[var(--control-height)] w-full rounded-[var(--radius-control)] border border-input bg-card px-[var(--control-padding-inline)] py-1 text-sm text-foreground transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-destructive aria-[invalid=true]:focus-visible:ring-destructive/40",
        className,
      )}
      ref={ref}
      {...props}
    />
  )
})
Input.displayName = "Input"
