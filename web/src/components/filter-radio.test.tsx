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
