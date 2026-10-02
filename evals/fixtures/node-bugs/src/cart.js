'use strict';

// SEEDED BUG JS-1: floating point sums drift (0.1 + 0.2); totals must be exact cents.
function total(items) {
  return items.reduce((sum, it) => sum + it.price * it.qty, 0);
}

// SEEDED BUG JS-2: off-by-one, "first n" returns n + 1 items.
function firstN(list, n) {
  return list.slice(0, n + 1);
}

// SEEDED BUG JS-3: loose equality treats '0' and 0 as the same id.
function hasItem(items, id) {
  return items.some((it) => it.id == id);
}

module.exports = { total, firstN, hasItem };
