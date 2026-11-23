import test from 'node:test'
import assert from 'node:assert/strict'
import { compareProposalCosts, comparisonPair, verifiedCost } from '../src/utils/proposalComparison.ts'

function option(currency, rail, other, total) {
  return { known_subtotals: { [currency]: total }, cost_items: [
    { kind: 'outbound', quality: 'verified_quote', amount: rail, currency },
    { kind: 'other', quality: 'user_budget', amount: other, currency },
  ] }
}

test('费用差只用范围相同的完整同币种金额，按精确分值计算', () => {
  const a = option('CNY', '308.05', '0', '308.05')
  const b = option('CNY', '301.99', '1.10', '303.090')
  assert.deepEqual(compareProposalCosts(a, b), { currency: 'CNY', delta: -4.96 })
  assert.deepEqual(compareProposalCosts(a, a), { currency: 'CNY', delta: 0 })
  assert.equal(compareProposalCosts(a, option('EUR', '301.99', '1.10', '303.09')), null)
  assert.equal(compareProposalCosts(a, { ...a, cost_items: [a.cost_items[0]] }), null)
})

test('缺项、参考价、不匹配小计、重复项目和混币都不冒充完整报价', () => {
  const a = option('CNY', '20', '1.20', '21.20')
  for (const altered of [
    option('CNY', null, '1.20', '21.20'),
    option('CNY', '20', '1.20', '20.20'),
    { ...a, cost_items: [...a.cost_items, a.cost_items[0]] },
    { ...a, cost_items: [{ ...a.cost_items[0], quality: 'reference' }, a.cost_items[1]] },
    { ...a, known_subtotals: { CNY: '20', USD: '1.20' } },
    { ...a, cost_items: [null, 1, ''] },
  ]) assert.equal(verifiedCost(altered), null)
})

test('零或单候选没有对比；预览 A、B 时列不换位，C 在同一参照下比较', () => {
  assert.equal(comparisonPair(0, 0), null)
  assert.equal(comparisonPair(1, 0), null)
  assert.deepEqual(comparisonPair(2, 0), [0, 1])
  assert.deepEqual(comparisonPair(2, 1), [0, 1])
  assert.deepEqual(comparisonPair(3, 2), [0, 2])
})
