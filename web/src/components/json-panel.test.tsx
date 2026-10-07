import {renderToStaticMarkup} from 'react-dom/server'
import {describe, expect, it} from 'vitest'
import {JsonPanel} from './json-panel'

describe('JSON output copy accessibility', () => {
  it.each(['复制', 'Copy'])('uses the supplied language label %s', copyLabel => {
    const html = renderToStaticMarkup(<JsonPanel data={{example:true}} copyLabel={copyLabel} />)
    expect(html).toContain(`aria-label="${copyLabel}"`)
  })
})
