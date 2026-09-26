import { Button, Input, InputNumber, Select } from "antd"
import type { InvokeCopy } from "./copy"
import { isRecord, owns, schemaFields, sensitiveField, supportsField, valueAt, type Arguments, type Field, type Schema } from "./schema"

type FormProps = { schema:Schema; value:Arguments; disabled:boolean; c:InvokeCopy; onChange:(path:string[],value:unknown)=>void; onJSON:()=>void }
const fieldType = (schema: Schema) => typeof schema.type === "string" ? `${schema.type}${schema.nullable ? " | null" : ""}` : "JSON"
const text = (value:unknown) => typeof value === "string" ? value : ""
const display = (value:unknown) => JSON.stringify(value)

function ArgumentField({ field,path,root,value,disabled,c,onChange,onJSON,depth=0 }: Omit<FormProps,"schema"|"value"> & {field:Field;path:string[];root:Schema;value:unknown;depth?:number}) {
  const {name,schema,required}=field
  const id=`invoke-field-${encodeURIComponent(JSON.stringify(path))}`
  const title=text(schema.title) || name
  const object=schema.type === "object" || isRecord(schema.properties)
  const supported=depth < 10 && supportsField(schema,value)
  const options=Array.isArray(schema.enum) ? schema.enum : schema.type === "boolean" ? [false,true] : null
  const common={id,disabled,"aria-describedby":`${id}-help`,"aria-required":required}
  const help=text(schema.description) || c.noDescription
  return <div className={`invoke-field ${object || (schema.type === "string" && !options) ? "invoke-field-wide" : ""}`}>
    <div className="invoke-field-label"><label htmlFor={id}>{title}{required && <span className="invoke-required" title={c.required}> *</span>}</label><code>{name}</code>{!required && value !== undefined && <Button type="link" size="small" disabled={disabled} onClick={()=>onChange(path,undefined)} aria-label={`${c.omit} ${name}`}>{c.omit}</Button>}</div>
    {!supported ? <div className="invoke-complex"><span>{c.complex}</span><Button id={id} type="link" size="small" onClick={onJSON}>{c.editJson}</Button></div>
      : value === null ? <div className="invoke-complex"><code>null</code><Button id={id} type="link" size="small" disabled={disabled} onClick={()=>onChange(path,object ? {} : schema.type === "boolean" ? false : ["integer","number"].includes(String(schema.type)) ? 0 : "")}>{c.setValue}</Button></div>
      : object ? <div className="invoke-nested">{value === undefined ? <Button id={id} disabled={disabled} onClick={()=>onChange(path,{})}>{c.addObject}</Button> : (schemaFields(schema,root) || []).map(child=><ArgumentField key={child.name} field={child} path={[...path,child.name]} root={root} value={valueAt(value,[child.name])} disabled={disabled} c={c} onChange={onChange} onJSON={onJSON} depth={depth+1}/>)}</div>
      : options ? <Select {...common} className="invoke-field-control" value={value === undefined ? undefined : display(value)} placeholder={required ? c.choose : c.omit} allowClear={!required} onChange={next=>onChange(path,next === undefined ? undefined : JSON.parse(next))} options={options.map(item=>({value:display(item),label:item === true ? c.true : item === false ? c.false : item === null ? c.null : typeof item === "string" ? item : display(item)}))}/>
      : schema.type === "integer" || schema.type === "number" ? <InputNumber {...common} className="invoke-field-control" value={typeof value === "number" ? value : null} step={schema.type === "integer" ? 1 : 0.1} placeholder={required ? c.enter : c.omit} onChange={next=>onChange(path,next === null ? undefined : next)}/>
      : <Input {...common} type={sensitiveField(name,schema) ? "password" : "text"} autoComplete="off" value={typeof value === "string" ? value : ""} placeholder={required ? c.enter : c.omit} onChange={event=>onChange(path,event.target.value)}/>}
    <p id={`${id}-help`} className="invoke-field-help">{help}</p>
    <div className="invoke-field-meta"><span>{fieldType(schema)}</span>{typeof schema.minimum === "number" && <span>≥ {schema.minimum}</span>}{typeof schema.maximum === "number" && <span>≤ {schema.maximum}</span>}{owns(schema,"default") && !sensitiveField(name,schema) && <span>{c.defaultValue}: <code>{display(schema.default)}</code></span>}{schema.nullable === true && value !== null && !options && <Button type="link" size="small" disabled={disabled} onClick={()=>onChange(path,null)}>{c.setNull}</Button>}</div>
  </div>
}

export function ArgumentForm({schema,value,...props}:FormProps) {
  const fields=schemaFields(schema)
  if (!fields) return <div className="invoke-blank">{props.c.unsupported}<Button type="link" onClick={props.onJSON}>{props.c.editJson}</Button></div>
  const unknown=Object.keys(value).filter(key=>!fields.some(field=>field.name === key))
  return <>
    {fields.length ? <div className="invoke-form-grid">{fields.map(field=><ArgumentField key={field.name} field={field} root={schema} path={[field.name]} value={valueAt(value,[field.name])} {...props}/>)}</div> : <div className="invoke-blank">{unknown.length ? props.c.unknownFields : schema.additionalProperties === false ? props.c.noParameters : props.c.noFixedFields}{schema.additionalProperties !== false && <Button type="link" onClick={props.onJSON}>{props.c.editJson}</Button>}</div>}
    {unknown.length > 0 && <div className="invoke-retained">{props.c.unknownFields} <code>{unknown.join(", ")}</code><Button type="link" size="small" onClick={props.onJSON}>{props.c.editJson}</Button></div>}
  </>
}

export function ArgumentReference({schema,c}:{schema:Schema;c:InvokeCopy}) {
  const fields=schemaFields(schema)
  return <aside className="invoke-reference" aria-label={c.docs}><p>{c.docHint}</p>{fields?.map(({name,schema,required})=><div className="invoke-reference-field" key={name}><div><strong>{text(schema.title) || name}</strong>{required && <span className="invoke-required">{c.required}</span>}<small>{fieldType(schema)}</small></div><code>{name}</code><p>{text(schema.description) || c.noDescription}</p>{!sensitiveField(name,schema) && owns(schema,"default") && <small>{c.defaultValue}: <code>{display(schema.default)}</code></small>}{!sensitiveField(name,schema) && Array.isArray(schema.examples) && schema.examples.length > 0 && <small>{c.sampleValue}: <code>{display(schema.examples[0])}</code></small>}</div>)}{!fields?.length && <p>{fields ? schema.additionalProperties === false ? c.noParameters : c.noFixedFields : c.unsupported}</p>}</aside>
}
