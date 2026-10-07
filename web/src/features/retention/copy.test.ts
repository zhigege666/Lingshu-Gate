import {describe, expect, it} from 'vitest'
import {retentionCopy} from './copy'

describe('recording and retention language coverage', () => {
  it('provides matching nonempty Chinese and English text for every control and confirmation', () => {
    const chinese = retentionCopy['zh-CN']
    const english = retentionCopy['en-US']
    expect(Object.keys(english).sort()).toEqual(Object.keys(chinese).sort())
    for (const key of Object.keys(chinese) as (keyof typeof chinese)[]) {
      expect(chinese[key].trim()).not.toBe('')
      expect(english[key].trim()).not.toBe('')
      expect(english[key]).not.toMatch(/[\u3400-\u9fff]/u)
    }
  })
  it('keeps each retention category and the default recording boundary explicit in both languages', () => {
    for (const text of Object.values(retentionCopy)) {
      expect(new Set([text.logs, text.events, text.calls]).size).toBe(3)
      expect(text.defaults).toContain('7')
      expect(text.metadata).toMatch(/默认|default/)
      expect(text.privacy).toMatch(/历史未记录内容无法补回|previously unrecorded content cannot be recovered/i)
    }
  })
})
