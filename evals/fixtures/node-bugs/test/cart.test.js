'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { total, firstN, hasItem } = require('../src/cart');

test('total is exact to the cent', () => {
  assert.strictEqual(total([{ price: 0.1, qty: 1 }, { price: 0.2, qty: 1 }]), 0.3);
});

test('firstN returns exactly n items', () => {
  assert.deepStrictEqual(firstN([1, 2, 3, 4], 2), [1, 2]);
});

test('hasItem does not coerce ids', () => {
  assert.strictEqual(hasItem([{ id: 0 }], '0'), false);
});
