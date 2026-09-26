import Ajv, { type ValidateFunction } from "ajv"
import Ajv2019 from "ajv/dist/2019"
import Ajv2020 from "ajv/dist/2020"
import addFormats from "ajv-formats"
import type { InvokeCopy } from "./copy"

export type Schema = Record<string, unknown>
export type Arguments = Record<string, unknown>
export const isRecord = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value)
export const owns = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key)
export const sensitiveField = (name: string, schema: Schema) => /password|passwd|secret|token|credential|authorization|cookie|api[_-]?key|private[_-]?key/i.test(name) || schema.writeOnly === true || schema.format === "password"

/** Resolve local references for presentation, without fetching remote schemas. */
export function resolveSchema(raw: unknown, root: Schema, seen = new Set<string>()): Schema {
  if (!isRecord(raw)) return { unsupported: true }
  if (typeof raw.$ref !== "string") return raw
  if (!raw.$ref.startsWith("#/") || seen.has(raw.$ref)) return { unsupported: true }
  const next = new Set(seen).add(raw.$ref)
  const target = raw.$ref.slice(2).split("/").reduce<unknown>((node, key) => isRecord(node) && owns(node,key.replace(/~1/g,"/").replace(/~0/g,"~")) ? node[key.replace(/~1/g,"/").replace(/~0/g,"~")] : undefined,root)
  const { $ref: _, ...rest } = raw
  return { ...resolveSchema(target,root,next), ...rest }
}

/** A nullable scalar/object is still editable; arbitrary unions remain JSON-only. */
export function fieldSchema(raw: unknown, root: Schema): Schema {
  const schema = resolveSchema(raw, root)
  if (Array.isArray(schema.anyOf) && schema.anyOf.length === 2) {
    const branches = schema.anyOf.map(branch => resolveSchema(branch,root))
    const nonNull = branches.filter(branch => branch.type !== "null")
    if (nonNull.length === 1) {
      const { anyOf: _, ...annotations } = schema
      return { ...nonNull[0], ...annotations, nullable: true }
    }
  }
  if (Array.isArray(schema.type) && schema.type.length === 2 && schema.type.includes("null")) return { ...schema, type: schema.type.find(type => type !== "null"), nullable: true }
  return schema
}
export type Field = { name: string; schema: Schema; required: boolean }
export function schemaFields(raw: Schema, root = raw): Field[] | null {
  const schema = fieldSchema(raw,root)
  if (schema.unsupported || schema.oneOf || schema.anyOf || schema.allOf || schema.if || (schema.type && schema.type !== "object")) return null
  return Object.entries(isRecord(schema.properties) ? schema.properties : {}).map(([name,property]) => ({ name, schema: fieldSchema(property,root), required: Array.isArray(schema.required) && schema.required.includes(name) }))
}

export type ParsedArguments = { ok: true; value: Arguments } | { ok: false; error: "invalidJson" | "objectRequired" }
export function parseArguments(text: string): ParsedArguments {
  try { const value: unknown = JSON.parse(text); return isRecord(value) ? { ok:true,value } : { ok:false,error:"objectRequired" } }
  catch { return { ok:false,error:"invalidJson" } }
}
export function valueAt(value: unknown,path: string[]): unknown {
  return path.reduce<unknown>((node,key) => isRecord(node) && owns(node,key) ? node[key] : undefined,value)
}
const put = (object: Arguments,key: string,value: unknown) => Object.defineProperty(object,key,{value,enumerable:true,writable:true,configurable:true})
export function changeArgument(text: string,path: string[],value: unknown): string | null {
  const parsed = parseArguments(text)
  if (!parsed.ok || path.length === 0) return null
  let node = parsed.value
  for (const key of path.slice(0,-1)) {
    if (!owns(node,key) || !isRecord(node[key])) put(node,key,{})
    node = node[key] as Arguments
  }
  const key = path[path.length-1]
  if (value === undefined) delete node[key]
  else put(node,key,value)
  return JSON.stringify(parsed.value,null,2)
}

export function createArgumentExample(root: Schema,mode: "example" | "defaults" = "example") {
  let declared = false
  const build = (raw: unknown,name: string,required: boolean,supplied?: unknown,hasSupplied = false,depth = 0): unknown => {
    const schema = fieldSchema(raw,root)
    if (depth > 12 || schema.unsupported || sensitiveField(name,schema)) return undefined
    let value = supplied, hasValue = hasSupplied
    if (!hasValue && owns(schema,"default")) { value=schema.default;hasValue=true;declared=true }
    else if (!hasValue && mode === "example" && Array.isArray(schema.examples) && schema.examples.length) { value=schema.examples[0];hasValue=true;declared=true }
    else if (!hasValue && owns(schema,"const")) { value=schema.const;hasValue=true;declared=true }
    if (schema.oneOf || schema.anyOf || schema.allOf || schema.if) return undefined
    if (hasValue && value === null) return null
    if (schema.type === "object" || schema.properties || (!name && !schema.type)) {
      if (!required && !hasValue) return undefined
      const result: Arguments = {}
      const object = isRecord(value) ? value : {}
      for (const [key,property] of Object.entries(isRecord(schema.properties) ? schema.properties : {})) {
        const next=build(property,key,Array.isArray(schema.required) && schema.required.includes(key),object[key],owns(object,key),depth+1)
        if (next !== undefined) put(result,key,next)
      }
      return result
    }
    if (!hasValue) return undefined
    if (Array.isArray(value)) {
      if (!isRecord(schema.items)) return undefined
      return value.map(item=>build(schema.items,name,true,item,true,depth+1)).filter(item=>item!==undefined)
    }
    // Only declared properties are copied from object annotations.
    if (isRecord(value)) return undefined
    return value
  }
  const value=build(root,"",true)
  return { text: JSON.stringify(isRecord(value) ? value : {},null,2), declared }
}

export function supportsField(schema: Schema,value: unknown) {
  if (schema.unsupported || schema.oneOf || schema.anyOf || schema.allOf || schema.if || owns(schema,"const")) return false
  if (schema.type === "object" && !Object.keys(isRecord(schema.properties) ? schema.properties : {}).length && schema.additionalProperties !== false) return false
  if (value === null) return schema.nullable === true
  if (Array.isArray(schema.enum)) return value === undefined || schema.enum.some(item=>JSON.stringify(item)===JSON.stringify(value))
  if (value !== undefined) {
    if ((schema.type === "object" || schema.properties) && !isRecord(value)) return false
    if (schema.type === "integer" && (typeof value !== "number" || !Number.isInteger(value))) return false
    if (["string","number","boolean"].includes(String(schema.type)) && typeof value !== schema.type) return false
  }
  return ["string","integer","number","boolean","object"].includes(String(schema.type)) || Boolean(schema.properties)
}

// No coercion, default injection, field removal, schema network requests, or parameter logging.
const options = { strict:false,allErrors:true,coerceTypes:false,useDefaults:false,removeAdditional:false,addUsedSchema:false,logger:false as const }
const validators = { legacy: addFormats(new Ajv(options)), draft2019: addFormats(new Ajv2019(options)), current: addFormats(new Ajv2020(options)) }
const compiled = new WeakMap<Schema,ValidateFunction | null>()
export function validateArguments(schema: Schema,text: string,c: InvokeCopy): { ok:true;value:Arguments } | { ok:false;error:string } {
  const parsed=parseArguments(text)
  if (!parsed.ok) return {ok:false,error:c[parsed.error]}
  let validate=compiled.get(schema)
  if (validate === undefined) {
    try {
      const dialect=typeof schema.$schema === "string" ? schema.$schema : ""
      const ajv=dialect.includes("draft-07") ? validators.legacy : dialect.includes("2019-09") ? validators.draft2019 : validators.current
      validate=ajv.compile(schema)
      if ("$async" in validate && validate.$async) validate=null
    } catch { validate=null }
    compiled.set(schema,validate)
  }
  if (!validate) return {ok:false,error:c.schemaInvalid}
  if (!validate(parsed.value)) {
    const error=validate.errors?.[0]
    const field=error?.params.missingProperty || error?.instancePath || c.json
    const detail=error?.keyword === "required" ? c.requiredError : error?.keyword === "type" ? c.typeError : ["minimum","maximum","exclusiveMinimum","exclusiveMaximum"].includes(error?.keyword || "") ? c.rangeError : error?.keyword === "enum" ? c.enumError : error?.keyword === "additionalProperties" ? `${c.unknownError}: ${String(error.params.additionalProperty)}` : c.invalidValue
    return {ok:false,error:`${String(field)}: ${detail}`}
  }
  return {ok:true,value:parsed.value}
}
