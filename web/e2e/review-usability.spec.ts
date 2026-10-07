import { test, expect } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'
import { translate } from '../src/i18n'

// These scenarios use explicit synthetic responses; they never activate OAuth or a tunnel.
for (const width of [1366, 390]) {
  test(`E2E-580-${width} @smoke connection guide retains saved progress and never claims live connectivity`, async ({ page }) => {
    await login(page)
    await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
    await page.setViewportSize({ width, height: 844 })
    let configuration = { enabled: false, mode: 'direct', endpoint: 'https://synthetic.example.com/mcp', canonical_resource_url: 'https://synthetic.example.com/mcp', tunnel_reference: null, runtime_secret_reference: null, trusted_issuers: ['https://issuer.example.com'], issuer_jwks: [['https://issuer.example.com', 'https://issuer.example.com/jwks']], client_allowlist: ['synthetic-client'], resource_mappings: [['https://synthetic.example.com/mcp', 'https://synthetic.example.com/mcp']], revision: 0, connected: false, provider_verified: false, oauth_verifier_ready: false }
    const writes: string[] = []
    await page.route('**/v1/auth/external-connection/config', async route => {
      if (route.request().method() === 'PUT') {
        const body=route.request().postDataJSON()
        expect(body.enabled).toBe(false)
        expect(body.expected_revision).toBe(configuration.revision)
        writes.push(route.request().url())
        configuration={...configuration,...body,revision:configuration.revision+1}
      }
      await route.fulfill({json:configuration})
    })
    await page.route('**/v1/auth/external-subject-links*', route=>route.fulfill({json:{links:[],total:0}}))
    await page.goto('/console/#/connectionInfrastructure')
    await page.getByRole('tab', { name: '外部身份提供方', exact: true }).click()
    await page.getByRole('button',{name:'接入引导',exact:true}).click()
    await expect(page.getByText('在哪里找配置',{exact:true})).toBeVisible()
    // The decorative loading icon can outlive a fast mocked response and the
    // reused footer button's step. Scope every action by role and visible label.
    const footerAction = (label: RegExp) => page.locator('.connection-guide-footer')
      .getByRole('button').filter({ hasText: label })
    const saveAction = footerAction(/^保存配置并继续$/)
    async function saveAndContinue(expectedRevision: number) {
      await expect(saveAction).not.toHaveClass(/ant-btn-loading/)
      const [response] = await Promise.all([
        page.waitForResponse(response => response.request().method() === 'PUT'
          && new URL(response.url()).pathname === '/v1/auth/external-connection/config'),
        saveAction.click(),
      ])
      expect(response.ok()).toBe(true)
      expect((await response.json()).revision).toBe(expectedRevision)
      expect(writes).toHaveLength(expectedRevision)
    }
    await saveAndContinue(1)
    await expect(page.getByText('受信 issuer（每行一个 HTTPS URL）',{exact:true})).toBeVisible()
    await saveAndContinue(2)
    await expect(page.getByText('OAuth 身份绑定',{exact:true})).toBeVisible()
    await footerAction(/^检查与验证$/).click()
    await expect(page.getByText('尚未验证外部连通与 ChatGPT 调用',{exact:true})).toBeVisible()
    const backAction = footerAction(/^返回总览$/)
    await expectInViewportAndUnobscured(backAction)
    expect(writes).toHaveLength(2)
    await backAction.click()
    await page.getByRole('button',{name:'接入引导',exact:true}).click()
    await expect(page.getByText('尚未验证外部连通与 ChatGPT 调用',{exact:true})).toBeVisible()
    expect(writes).toHaveLength(2)
  })
}

test('E2E-582 @smoke credential search distinguishes no match from no authorized slots',async({page})=>{
 await login(page)
 await page.route('**/v1/auth/downstream-credentials',route=>route.fulfill({json:{credentials:[{server_id:'synthetic',server_name:'Synthetic service',id:'sample-slot',name:'Synthetic access key',description:'Metadata only',transport_type:'streamable_http',required:true,configured:false,injection:{type:'http_header',name:'Authorization',template:'Bearer {value}'}}]}}))
 await page.goto('/console/#/downstreamCredentials')
 await expect(page.getByText('Synthetic service',{exact:true})).toBeVisible()
 const search = page.getByRole('textbox',{name:'Search service, purpose or header',exact:true})
 await search.fill('no-matching-credential')
 await expect(page.getByText(translate('en-US','noCurrentMatches'),{exact:true})).toBeVisible()
 await expect(page.getByText('No user credential slots are declared for your granted resources',{exact:true})).toHaveCount(0)
 await page.getByRole('button',{name:translate('en-US','resetFilters'),exact:true}).click()
 await expect(search).toHaveValue('')
 await expect(page.getByText('Synthetic service',{exact:true})).toBeVisible()
})
