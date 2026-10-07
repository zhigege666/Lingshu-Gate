import {renderToStaticMarkup} from 'react-dom/server'
import {describe, expect, it} from 'vitest'
import {ConfigsPage} from './configs-page'
import {translate, type Locale, type TFunction} from '@/i18n'

const noop = () => {}
describe('configuration runtime labels', () => {
  it.each([
    ['zh-CN', ['受管 Stdio', '受管 HTTP', '外部 HTTP', '高级模式']],
    ['en-US', ['Managed Stdio', 'Managed HTTP', 'External HTTP', 'Advanced Mode']],
  ] as [Locale,string[]][])('renders all modes in %s', (locale, labels) => {
    const t:TFunction = key => translate(locale,key)
    const configs = [
      ['managed_process','stdio'], ['managed_process','streamable_http'],
      ['external','streamable_http'], ['managed_container','stdio'],
    ].map(([launch,transport],i)=>({id:`synthetic-${i}`,path:`synthetic-${i}.json`,format:'json',manifest:{id:`synthetic-${i}`,launch:{type:launch},transport:{type:transport}}}))
    const html=renderToStaticMarkup(<ConfigsPage locale={locale} t={t} configs={configs} configErrors={[]} selectedConfigId="" configText="" busy={false} editorOpen={false} onCloseEditor={noop} onNewConfig={noop} onReloadConfigs={noop} onEditConfig={noop} onApplyConfig={noop} onDeleteConfig={noop} onConfigTextChange={noop} onSaveConfig={async()=>{}} />)
    for(const label of labels) expect(html).toContain(label)
  })
})
