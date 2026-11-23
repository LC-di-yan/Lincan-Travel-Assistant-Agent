import test from 'node:test'
import assert from 'node:assert/strict'
import { expenseTotals, originalAmount } from '../src/utils/expenseEvidence.ts'

test('费用保留原币、负数和明确的零；缺少金额或币种不猜测', () => {
  assert.equal(originalAmount(-12.3, 'USD'), 'USD -12.30')
  assert.equal(originalAmount('12.345', 'KWD'), 'KWD 12.345')
  assert.equal(originalAmount(0, 'CNY'), 'CNY 0.00')
  assert.equal(originalAmount(null, 'CNY'), '金额未提供')
  assert.equal(originalAmount(12, null), '12.00 · 币种未提供')
})

test('单币种和混币汇总都以币种明细为准，不使用合并后金额', () => {
  assert.deepEqual(expenseTotals({ EUR: 8.9 }, { amount: 0, currency: 'CNY' }), [{ currency: 'EUR', display: 'EUR 8.90' }])
  assert.deepEqual(expenseTotals({ USD: -12, CNY: 64 }), [
    { currency: 'USD', display: 'USD -12.00' }, { currency: 'CNY', display: 'CNY 64.00' },
  ])
  assert.deepEqual(expenseTotals({ OTHER: 8 }, { amount: 8, currency: 'CNY' }), [])
})
