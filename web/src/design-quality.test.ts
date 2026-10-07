import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const provider=readFileSync(new URL('./components/console-design-provider.tsx',import.meta.url),'utf8')
const base=readFileSync(new URL('./index.css',import.meta.url),'utf8')
const shell=readFileSync(new URL('./console-workspace.css',import.meta.url),'utf8')
function luminance(hex:string) {
 const rgb=hex.slice(1).match(/../g)!.map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
 return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722
}
function contrast(a:string,b:string){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
describe('console visual quality guardrails (source checks, not visual acceptance)',()=>{
 it.each(['Success','Warning','Error'])('%s text tokens retain 4.5:1 contrast on their theme surfaces',role=>{
  const match=provider.match(new RegExp(`color${role}: mode === "dark" \\? "(#[0-9a-f]+)" : "(#[0-9a-f]+)"`))!
  expect(match).not.toBeNull()
  expect(contrast(match[1],'#131a24')).toBeGreaterThanOrEqual(4.5)
  expect(contrast(match[2],'#ffffff')).toBeGreaterThanOrEqual(4.5)
 })
 it('CJK sans fallback is shared by native and AntD controls',()=>{
  expect(base).toContain('"Noto Sans CJK SC"')
  expect(provider).toContain('"Noto Sans CJK SC"')
 })
 it('motion remains short, respects reduced motion and does not animate every row into place',()=>{
  expect(base).toContain('--motion-fast: 120ms')
  expect(shell).toContain('@media (prefers-reduced-motion: reduce)')
  expect(shell).toContain('animation-duration: .01ms !important')
  expect(shell).not.toMatch(/tbody[^}]*animation:/)
 })
})
