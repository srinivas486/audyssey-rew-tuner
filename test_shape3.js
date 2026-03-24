async function test() {
  const mRes = await fetch('http://localhost:4735/measurements');
  const mList = await mRes.json();
  const keys = Object.keys(mList);
  const uuid = mList[keys[keys.length-1]].uuid; // Get SW2
  
  // Set shape to Subwoofer
  await fetch('http://localhost:4735/measurements/' + uuid + '/target-settings', {
     method: 'POST',
     headers:{ 'Content-Type':'application/json' },
     body: JSON.stringify({ shape: 'Subwoofer', type: 'Speaker', addRoomCurve: true })
  });
  
  // Calculate target level
  await fetch('http://localhost:4735/measurements/' + uuid + '/eq/command', {
    method: 'POST',
    headers:{ 'Content-Type':'application/json' },
    body: JSON.stringify({ command: 'Calculate target level' })
  });

  // Now set filter tasks
  const ftres = await fetch('http://localhost:4735/measurements/' + uuid + '/eq/filter-tasks', { method: 'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify({ manufacturer: 'Generic', model: 'Generic', matchRangeStart: 20, matchRangeEnd: 250, maxMatchBoost: 3, maxOverallBoost: 3, individualMaxBoost: 3 }) });
  console.log("Filter Tasks:", ftres.status, await ftres.text());
}
test().catch(console.error);
