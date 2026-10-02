import { test, expect } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'

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
    await page.getByRole('button',{name:'接入引导',exact:true}).click()
    await expect(page.getByText('在哪里找配置',{exact:true})).toBeVisible()
    await page.getByRole('button',{name:'保存配置并继续',exact:true}).click()
    await expect(page.getByText('受信 issuer（每行一个 HTTPS URL）',{exact:true})).toBeVisible()
    await page.getByRole('button',{name:'保存配置并继续',exact:true}).click()
    await expect(page.getByText('OAuth 身份绑定',{exact:true})).toBeVisible()
    await page.getByRole('button',{name:'检查与验证',exact:true}).click()
    await expect(page.getByText('尚未验证外部连通与 ChatGPT 调用',{exact:true})).toBeVisible()
    await expectInViewportAndUnobscured(page.locator('.connection-guide-footer').getByRole('button',{name:'返回总览',exact:true}))
    expect(writes).toHaveLength(2)
    await page.locator('.connection-guide-footer').getByRole('button',{name:'返回总览',exact:true}).click()
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
 await page.getByRole('textbox',{name:'Search service, purpose or header',exact:true}).fill('no-matching-credential')
 const {translate}=await import('../src/i18n')
 await expect(page.getByText(translate('en-US','noCurrentMatches'),{exact:true})).toBeVisible()
 await expect(page.getByText('No user credential slots are declared for your granted resources',{exact:true})).toHaveCount(0)
 await page.getByRole('button',{name:'Reset filters',exact:true}).click()
 await expect(page.getByText('Synthetic service',{exact:true})).toBeVisible()
})
