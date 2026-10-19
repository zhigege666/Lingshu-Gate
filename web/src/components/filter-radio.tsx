import { useId, type ReactNode } from "react"
import "./filter-radio.css"
/** Small, fixed filter sets stay visible and keyboard-operable without a popup. */
export function FilterRadio({ label, value, options, onChange, disabled = false, hideLabel = false, id, className = "", ...aria }: {
  label: string; value: string; options: Array<{ value: string; label: ReactNode }>;
  onChange: (value: string) => void; disabled?: boolean
  hideLabel?: boolean; id?: string; className?: string
  "aria-describedby"?: string; "aria-invalid"?: boolean; "aria-required"?: boolean
}) {
  const name = useId()
  return <div className={`filter-radio ${className}`} role="radiogroup" aria-label={label} {...aria}>
    {!hideLabel && <span className="filter-radio-label">{label}</span>}
    {options.map((option, index) => <label key={option.value} data-selected={option.value === value}>
      <input id={id ? index === 0 ? id : `${id}-${index}` : undefined} type="radio" name={name} value={option.value} checked={value === option.value} disabled={disabled} aria-describedby={aria["aria-describedby"]} aria-invalid={aria["aria-invalid"]} onChange={() => onChange(option.value)} />
      <span>{option.label}</span>
    </label>)}
  </div>
}
