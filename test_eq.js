const fs = require('fs');

async function test() {
  const req = await fetch('http://localhost:4735/measurements/1/eq/filter-tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      manufacturer: 'Generic',
      model: 'Generic',
      matchRangeStart: 20,
      matchRangeEnd: 20000,
      maxMatchBoost: 3,
      maxOverallBoost: 3,
      individualMaxBoost: 3
    })
  });
  console.log(req.status, await req.text());
}
test().catch(console.error);
