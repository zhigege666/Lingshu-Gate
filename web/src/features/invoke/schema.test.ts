import { describe,expect,it } from "vitest"
import { invokeCopy } from "./copy"
import { changeArgument,createArgumentExample,fieldSchema,parseArguments,schemaFields,supportsField,validateArguments,type Schema } from "./schema"
const c=invokeCopy("en-US")
const search:Schema={type:"object",properties:{query:{type:"string",minLength:1,examples:["MCP configuration"]},limit:{type:"integer",minimum:1,maximum:100,default:10},archived:{type:"boolean",default:false}},required:["query"],additionalProperties:false}

describe("tool argument schema editing",()=>{
  it("uses declared defaults and examples, without inventing missing required values",()=>{
    expect(JSON.parse(createArgumentExample(search).text)).toEqual({query:"MCP configuration",limit:10,archived:false})
    const defaults=createArgumentExample(search,"defaults")
    expect(JSON.parse(defaults.text)).toEqual({limit:10,archived:false})
    expect(validateArguments(search,defaults.text,c).ok).toBe(false)
    expect(createArgumentExample({type:"object",required:["id"],properties:{id:{type:"string"}}}).text).toBe("{}")
  })
  it("keeps false, zero, null and nested declared examples",()=>{
    const schema={type:"object",properties:{enabled:{type:"boolean",default:false},offset:{type:"integer",default:0},query:{anyOf:[{type:"string"},{type:"null"}],default:null},filter:{type:"object",examples:[{status:"active"}],properties:{status:{type:"string"}}}}}
    expect(JSON.parse(createArgumentExample(schema).text)).toEqual({enabled:false,offset:0,query:null,filter:{status:"active"}})
  })
  it("strips sensitive values from nested and array annotations",()=>{
    const schema={type:"object",examples:[{password:"do-not-copy",profile:{name:"example",api_key:"do-not-copy"},users:[{name:"example",secret:"do-not-copy"}]}],properties:{password:{type:"string"},profile:{type:"object",properties:{name:{type:"string"},api_key:{type:"string"}}},users:{type:"array",items:{type:"object",properties:{name:{type:"string"},secret:{type:"string"}}}}}}
    expect(JSON.parse(createArgumentExample(schema).text)).toEqual({profile:{name:"example"},users:[{name:"example"}]})
  })
  it("preserves unknown keys and sibling values while editing or omitting one field",()=>{
    const input='{"extra":{"keep":true},"filter":{"value":4,"enabled":false}}'
    const updated=changeArgument(input,["filter","value"],0)!
    expect(JSON.parse(updated)).toEqual({extra:{keep:true},filter:{value:0,enabled:false}})
    expect(JSON.parse(changeArgument(updated,["filter","value"],undefined)!)).toEqual({extra:{keep:true},filter:{enabled:false}})
    expect(JSON.parse(changeArgument(updated,["filter","value"],"")!).filter.value).toBe("")
  })
  it("rejects malformed and non-object JSON without replacing it",()=>{
    for (const input of ['{"query":',"null","[]","1"]) {
      expect(parseArguments(input).ok).toBe(false)
      expect(changeArgument(input,["query"],"replacement")).toBeNull()
    }
  })
  it("resolves annotated local refs and nullable fields without guessing unions",()=>{
    const schema={type:"object",properties:{value:{$ref:"#/$defs/item",title:"Value"}},required:["value"],$defs:{item:{anyOf:[{type:"string",description:"Search"},{type:"null"}]}}}
    const fields=schemaFields(schema)!
    expect(fields[0].required).toBe(true)
    expect(fields[0].schema).toMatchObject({title:"Value",type:"string",description:"Search",nullable:true})
    expect(supportsField(fields[0].schema,null)).toBe(true)
    expect(supportsField({anyOf:[{type:"string"},{type:"number"}]},"1")).toBe(false)
    expect(fieldSchema({$ref:"#/$defs/cycle"},{$defs:{cycle:{$ref:"#/$defs/cycle"}}}).unsupported).toBe(true)
  })
  it("does not coerce mismatched values or drop unsupported arrays",()=>{
    expect(supportsField({type:"integer"},"12")).toBe(false)
    expect(supportsField({type:"array"},[])).toBe(false)
    expect(supportsField({type:"object",additionalProperties:{type:"string"}},{key:"value"})).toBe(false)
    expect(supportsField({enum:[1,"1"]},1)).toBe(true)
    expect(supportsField({enum:[1]},"1")).toBe(false)
  })
  it("blocks missing, invalid, unknown and out-of-range arguments",()=>{
    for(const input of ["{}",'{"query":""}','{"query":"ok","limit":101}','{"query":"ok","archived":"false"}','{"query":"ok","extra":1}']) expect(validateArguments(search,input,c).ok).toBe(false)
    expect(validateArguments(search,'{"query":"ok","archived":false}',c).ok).toBe(true)
  })
  it("uses the declared schema dialect, and does not fetch unknown references",()=>{
    expect(validateArguments({...search,$schema:"http://json-schema.org/draft-07/schema#"},'{"query":"ok"}',c).ok).toBe(true)
    expect(validateArguments({...search,$schema:"https://json-schema.org/draft/2019-09/schema"},'{"query":"ok"}',c).ok).toBe(true)
    expect(validateArguments({...search,$schema:"https://json-schema.org/draft/2020-12/schema"},'{"query":"ok"}',c).ok).toBe(true)
    expect(validateArguments({$ref:"https://example.invalid/schema"},"{}",c)).toEqual({ok:false,error:c.schemaInvalid})
  })
  it("keeps schema IDs isolated and rejects async validators",()=>{
    expect(validateArguments({$id:"urn:tool:one",type:"object"},"{}",c).ok).toBe(true)
    expect(validateArguments({$id:"urn:tool:one",type:"object",required:["q"]},"{}",c).ok).toBe(false)
    expect(validateArguments({$async:true,type:"object"},"{}",c)).toEqual({ok:false,error:c.schemaInvalid})
  })
  it("protects prototypes and literal dots in parameter names",()=>{
    const updated=changeArgument('{}',["__proto__","polluted"],true)!
    expect(({} as Record<string,unknown>).polluted).toBeUndefined()
    expect(JSON.parse(updated).__proto__.polluted).toBe(true)
    expect(JSON.parse(changeArgument('{}',["a.b"],0)!)).toEqual({"a.b":0})
  })
})
