import { parseGenToWei, formatWeiToGen } from '../money.js';

function assert(cond, msg) {
  if (!cond) {
    throw new Error(msg);
  }
}

function runUnitConversionTests() {
  console.log('Starting Precision Unit Conversion Tests...');

  const smallestWei = parseGenToWei('0.000000000000000001');
  assert(smallestWei === 1n, `Test 1 Failed: expected 1n, got ${smallestWei}`);
  assert(formatWeiToGen(1n) === '0.000000000000000001', `Test 1 Format Failed: got ${formatWeiToGen(1n)}`);

  const pointOneWei = parseGenToWei('0.1');
  assert(pointOneWei === 100000000000000000n, `Test 2 Failed: got ${pointOneWei}`);
  assert(formatWeiToGen(100000000000000000n) === '0.1', `Test 2 Format Failed`);

  const millionWei = parseGenToWei('1000000');
  assert(millionWei === 1000000000000000000000000n, `Test 3 Failed: got ${millionWei}`);
  assert(formatWeiToGen(1000000000000000000000000n) === '1000000', `Test 3 Format Failed`);

  const testValues = ['1', '0.5', '100.25', '0.000001', '30000'];
  for (const val of testValues) {
    const wei = parseGenToWei(val);
    const formatted = formatWeiToGen(wei);
    assert(formatted === val, `Round-trip Failed for ${val}: got ${formatted}`);
  }

  assert(parseGenToWei('') === 0n, 'empty should be 0n');
  assert(parseGenToWei('abc') === 0n, 'invalid should be 0n');
  assert(formatWeiToGen(0n) === '0', 'zero format');

  console.log('All precision unit conversion tests passed.');
}

runUnitConversionTests();
