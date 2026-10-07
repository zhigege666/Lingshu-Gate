import { useId, type ReactNode } from "react"
import "./filter-radio.css"
/** Small, fixed filter sets stay visible and keyboard-operable without a popup. */
export function FilterRadio({ label, value, options, onChange, disabled = false }: {
  label: string; value: string; options: Array<{ value: string; label: ReactNode }>;
  onChange: (value: string) => void; disabled?: boolean
}) {
  const name = useId()
  return <div className="filter-radio" role="radiogroup" aria-label={label}>
    <span className="filter-radio-label">{label}</span>
    {options.map(option => <label key={option.value} data-selected={option.value === value}>
      <input type="radio" name={name} value={option.value} checked={value === option.value} disabled={disabled} onChange={() => onChange(option.value)} />
      <span>{option.label}</span>
    </label>)}
  </div>
}
