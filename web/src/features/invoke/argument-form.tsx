import { useState } from "react"
import { Button, Input, InputNumber, Select } from "antd"
import { Plus, Trash2 } from "lucide-react"
import { pointerFor, type ValidationIssue } from "@/lib/validation"
import type { InvokeCopy } from "./copy"
import { emptyFieldValue, fieldSchema, isRecord, owns, schemaFields, sensitiveField, supportsField, valueAt, type Arguments, type Field, type Schema } from "./schema"
import type { PendingArgumentEntries } from "./model"

type FormProps = { schema:Schema; value:Arguments; disabled:boolean; c:InvokeCopy; issues?:ValidationIssue[]; pendingEntries:PendingArgumentEntries; onPendingEntryChange:(path:string[],value:string)=>void; onChange:(path:string[],value:unknown)=>boolean|void; onJSON:()=>void }
type FieldProps = Omit<FormProps,"schema"|"value"> & {field:Field;path:string[];root:Schema;value:unknown;depth?:number}
const fieldType = (schema: Schema) => typeof schema.type === "string" ? `${schema.type}${schema.nullable ? " | null" : ""}` : "JSON"
const text = (value:unknown) => typeof value === "string" ? value : ""
const display = (value:unknown) => JSON.stringify(value)
export const argumentFieldId = (path:string[]) => `invoke-field-${encodeURIComponent(JSON.stringify(path))}`

/** Array updates are whole-array transactions; row identities survive removal. */
function ArrayField(props:FieldProps) {
  const {field:{schema,name},value,path,root,c,disabled,onChange}=props
  const values=Array.isArray(value) ? value : []
  const [rowIds,setRowIds]=useState<number[]>(()=>values.map((_,index)=>index))
  const [nextId,setNextId]=useState(values.length)
  const itemSchema=fieldSchema(schema.items,root)
  const ids=values.map((_,index)=>rowIds[index] ?? nextId+index)
  return <div className="invoke-collection">
    {values.map((item,index)=><div className="invoke-array-row" key={ids[index]}>
      <ArgumentField {...props} field={{name:`${c.item} ${index+1}`,schema:itemSchema,required:true}} path={[...path,String(index)]} value={item} depth={(props.depth || 0)+1}/>
      <Button className="invoke-remove-row" type="text" icon={<Trash2 size={15}/>} disabled={disabled} aria-label={`${c.removeItem} ${name} ${index+1}`} onClick={()=>{if (onChange(path,values.filter((_,position)=>position !== index)) !== false) setRowIds(ids.filter((_,position)=>position !== index))}}/>
    </div>)}
    <Button id={argumentFieldId(path)} icon={<Plus size={15}/>} disabled={disabled} onClick={()=>{if (onChange(path,[...values,emptyFieldValue(itemSchema)]) === false) return;setRowIds([...ids,Math.max(nextId,...ids.map(id=>id+1))]);setNextId(Math.max(nextId,...ids.map(id=>id+1))+1)}}>{c.addItem}</Button>
    {value === undefined && <Button type="link" disabled={disabled} onClick={()=>onChange(path,[])}>{c.useEmptyArray}</Button>}
  </div>
}

/** Only typed maps are editable here; arbitrary JSON maps keep their raw editor. */
function MapField(props:FieldProps) {
  const {field:{schema},value,path,root,c,disabled,onChange,pendingEntries,onPendingEntryChange}=props
  const newKey=pendingEntries[pointerFor(path)] || ""
  const [keyError,setKeyError]=useState<string|null>(null)
  const values=isRecord(value) ? value : {}
  const itemSchema=fieldSchema(schema.additionalProperties,root)
  const pendingError=Boolean(newKey && props.issues?.some(issue=>issue.code === "pendingEntry" && issue.path === pointerFor(path)))
  function add() {
    if (!newKey) {setKeyError(c.emptyKey);return}
    if (owns(values,newKey)) {setKeyError(c.duplicateKey);return}
    if (onChange([...path,newKey],emptyFieldValue(itemSchema)) === false) return
    onPendingEntryChange(path,"");setKeyError(null)
  }
  const id=argumentFieldId(path)
  return <div className="invoke-collection">
    {Object.entries(values).map(([key,item])=><div className="invoke-array-row" key={key}>
      <ArgumentField {...props} field={{name:key,schema:itemSchema,required:true}} path={[...path,key]} value={item} depth={(props.depth || 0)+1}/>
      <Button className="invoke-remove-row" type="text" icon={<Trash2 size={15}/>} disabled={disabled} aria-label={`${c.removeItem} ${key}`} onClick={()=>onChange([...path,key],undefined)}/>
    </div>)}
    <div className="invoke-map-add"><label className="sr-only" htmlFor={id}>{c.mapKey}</label><Input id={id} value={newKey} disabled={disabled} placeholder={c.mapKey} aria-invalid={Boolean(keyError) || pendingError} aria-describedby={keyError ? `${id}-key-error` : newKey ? `${id}-pending-hint` : undefined} onChange={event=>{onPendingEntryChange(path,event.target.value);setKeyError(null)}} onPressEnter={event=>{event.preventDefault();add()}}/><Button icon={<Plus size={15}/>} disabled={disabled} onClick={add}>{c.addKey}</Button></div>
    {newKey && <div className="invoke-pending-entry"><p id={`${id}-pending-hint`} className={pendingError ? "invoke-field-error" : undefined}>{c.pendingEntryHint}</p><Button type="link" size="small" disabled={disabled} onClick={()=>{onPendingEntryChange(path,"");setKeyError(null)}}>{c.clearPendingEntry}</Button></div>}
    {value === undefined && <Button type="link" disabled={disabled} onClick={()=>onChange(path,{})}>{c.useEmptyObject}</Button>}
    {keyError && <p className="invoke-field-error" id={`${id}-key-error`} role="alert">{keyError}</p>}
  </div>
}

function ArgumentField({ field,path,root,value,disabled,c,onChange,onJSON,pendingEntries,onPendingEntryChange,issues=[],depth=0 }: FieldProps) {
  const {name,schema,required}=field
  const id=argumentFieldId(path)
  const title=text(schema.title) || name
  const sensitive=sensitiveField(path.join("."),schema)
  const object=schema.type === "object" || isRecord(schema.properties)
  const supported=depth < 10 && supportsField(schema,value,root)
  const options=Array.isArray(schema.enum) ? schema.enum : schema.type === "boolean" ? [false,true] : null
  const errors=issues.filter(issue=>issue.path === pointerFor(path))
  const help=text(schema.description)
  const common={id,disabled,"aria-describedby":[help ? `${id}-help` : "",errors.length ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined,"aria-required":required,"aria-invalid":errors.length > 0}
  const childProps={field,path,root,value,disabled,c,onChange,onJSON,issues,depth,pendingEntries,onPendingEntryChange}
  const fields=object ? schemaFields(schema,root) || [] : []
  const map=object && !fields.length && isRecord(schema.additionalProperties)
  // The rendered map owns its pending-row message, including at the root.
  const displayErrors=errors.filter(issue=>!(issue.code === "pendingEntry" && supported && map && value !== null && pendingEntries[pointerFor(path)]))
  const unknown=object && !map && isRecord(value) ? Object.keys(value).filter(key=>!fields.some(child=>child.name === key)) : []
  return <div className="invoke-field">
    <div className="invoke-field-label"><label htmlFor={id}>{title}{required && <span className="invoke-required" title={c.required}> *</span>}</label>{title !== name && <code>{name}</code>}{!required && value !== undefined && <Button type="link" size="small" disabled={disabled} onClick={()=>onChange(path,undefined)} aria-label={`${c.omit} ${name}`}>{c.omit}</Button>}</div>
    {!supported ? <div className="invoke-complex"><span>{c.complex}</span><Button id={id} type="link" size="small" disabled={disabled} onClick={onJSON}>{c.editJson}</Button></div>
      : value === null ? <div className="invoke-complex"><span>{c.null}</span>{(!Array.isArray(schema.enum) || schema.enum.some(item=>item !== null)) && <Button id={id} type="link" size="small" disabled={disabled} onClick={()=>onChange(path,emptyFieldValue(schema))}>{c.setValue}</Button>}</div>
      : schema.type === "array" ? <ArrayField {...childProps}/>
      : map ? <MapField {...childProps}/>
      : object ? <div className="invoke-nested">{value === undefined ? <Button id={id} disabled={disabled} onClick={()=>onChange(path,{})}>{c.addObject}</Button> : <><div id={id} tabIndex={-1}/>{fields.map(child=><ArgumentField key={child.name} field={child} path={[...path,child.name]} root={root} value={valueAt(value,[child.name])} disabled={disabled} c={c} onChange={onChange} onJSON={onJSON} issues={issues} depth={depth+1} pendingEntries={pendingEntries} onPendingEntryChange={onPendingEntryChange}/>)}</>}{unknown.length > 0 && <div className="invoke-retained">{c.unknownFields} <code>{unknown.join(", ")}</code><Button type="link" size="small" disabled={disabled} onClick={onJSON}>{c.editJson}</Button></div>}</div>
      : options ? <Select {...common} className="invoke-field-control" value={value === undefined ? undefined : display(value)} placeholder={required ? c.choose : c.omit} allowClear={!required} onChange={next=>onChange(path,next === undefined ? undefined : JSON.parse(next))} options={options.map(item=>({value:display(item),label:item === true ? c.true : item === false ? c.false : item === null ? c.null : typeof item === "string" ? item : display(item)}))}/>
      : schema.type === "integer" || schema.type === "number" ? <InputNumber {...common} className="invoke-field-control" value={typeof value === "number" ? value : null} step={schema.type === "integer" ? 1 : 0.1} placeholder={required ? c.enter : c.omit} onChange={next=>onChange(path,next === null ? undefined : next)}/>
      : <Input {...common} type={sensitive ? "password" : "text"} autoComplete="off" value={typeof value === "string" ? value : ""} placeholder={required ? c.enter : c.omit} onChange={event=>onChange(path,event.target.value)}/>}
    {help && <p id={`${id}-help`} className="invoke-field-help">{help}</p>}
    {displayErrors.length > 0 && <p id={`${id}-error`} className="invoke-field-error">{displayErrors.map(issue=>issue.message).join("; ")}</p>}
    <div className="invoke-field-meta"><span>{fieldType(schema)}</span>{typeof schema.minimum === "number" && <span>≥ {schema.minimum}</span>}{typeof schema.maximum === "number" && <span>≤ {schema.maximum}</span>}{owns(schema,"default") && !sensitive && <span>{c.defaultValue}: <code>{display(schema.default)}</code></span>}{schema.nullable === true && value !== null && !options && <Button type="link" size="small" disabled={disabled} onClick={()=>onChange(path,null)}>{c.setNull}</Button>}</div>
  </div>
}

export function ArgumentForm({schema,value,...props}:FormProps) {
  const fields=schemaFields(schema)
  if (!fields) return <div className="invoke-blank">{props.c.unsupported}<Button type="link" onClick={props.onJSON}>{props.c.editJson}</Button></div>
  if (!fields.length && isRecord(schema.additionalProperties) && supportsField(schema,value,schema)) return <MapField {...props} field={{name:props.c.configure,schema,required:true}} path={[]} root={schema} value={value}/>
  const unknown=Object.keys(value).filter(key=>!fields.some(field=>field.name === key))
  return <>
    {fields.length ? <div className="invoke-form-grid">{fields.map(field=><ArgumentField key={field.name} field={field} root={schema} path={[field.name]} value={valueAt(value,[field.name])} {...props}/>)}</div> : <div className="invoke-blank">{unknown.length ? props.c.unknownFields : schema.additionalProperties === false ? props.c.noParameters : props.c.noFixedFields}{schema.additionalProperties !== false && <Button type="link" onClick={props.onJSON}>{props.c.editJson}</Button>}</div>}
    {unknown.length > 0 && <div className="invoke-retained">{props.c.unknownFields} <code>{unknown.join(", ")}</code><Button type="link" size="small" onClick={props.onJSON}>{props.c.editJson}</Button></div>}
  </>
}

export function ArgumentReference({schema,c}:{schema:Schema;c:InvokeCopy}) {
  const fields=schemaFields(schema)
  return <aside className="invoke-reference" aria-label={c.docs}><p>{c.docHint}</p>{fields?.map(({name,schema,required})=><div className="invoke-reference-field" key={name}><div><strong>{text(schema.title) || name}</strong>{required && <span className="invoke-required">{c.required}</span>}<small>{fieldType(schema)}</small></div>{text(schema.title) && <code>{name}</code>}{text(schema.description) && <p>{text(schema.description)}</p>}{!sensitiveField(name,schema) && owns(schema,"default") && <small>{c.defaultValue}: <code>{display(schema.default)}</code></small>}{!sensitiveField(name,schema) && Array.isArray(schema.examples) && schema.examples.length > 0 && <small>{c.sampleValue}: <code>{display(schema.examples[0])}</code></small>}</div>)}{!fields?.length && <p>{fields ? schema.additionalProperties === false ? c.noParameters : c.noFixedFields : c.unsupported}</p>}</aside>
}
