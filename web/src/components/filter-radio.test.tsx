import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"
import { FilterRadio } from "./filter-radio"
it("renders all fixed choices without a popup and defaults to one selected value",()=>{
 const html=renderToStaticMarkup(<FilterRadio label="决策" value="all" options={[{value:"all",label:"全部"},{value:"allow",label:"允许"},{value:"deny",label:"拒绝"}]} onChange={()=>{}} />)
 expect(html).toContain('role="radiogroup"')
 expect(html.match(/type="radio"/g)).toHaveLength(3)
 expect(html.match(/checked=""/g)).toHaveLength(1)
 expect(html).toContain("全部")
 expect(html).toContain("允许")
 expect(html).toContain("拒绝")
})

it("keeps a hidden visual label accessible and exposes the first choice as the form focus target", () => {
  const html = renderToStaticMarkup(<FilterRadio id="choice" label="Choice" hideLabel value="" disabled aria-required aria-invalid aria-describedby="choice-help choice-error" options={[{ value: "false", label: "No" }, { value: "true", label: "Yes" }]} onChange={() => {}} />)
  expect(html).toContain('role="radiogroup" aria-label="Choice"')
  expect(html).not.toContain('class="filter-radio-label"')
  expect(html).toContain('id="choice"')
  expect(html).toContain('id="choice-1"')
  expect(html).toContain('aria-required="true"')
  expect(html.match(/aria-describedby="choice-help choice-error"/g)).toHaveLength(3)
  expect(html.match(/disabled=""/g)).toHaveLength(2)
  expect(html).not.toContain('checked=""')
})
