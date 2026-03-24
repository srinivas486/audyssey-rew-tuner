async function test() {
  const mRes = await fetch('http://localhost:4735/measurements');
  const mList = await mRes.json();
  const keys = Object.keys(mList);
  const uuid = mList[keys[keys.length-1]].uuid; // Get SW2
  
  const r = await fetch('http://localhost:4735/measurements/' + uuid + '/target-settings', {
     method: 'POST',
     headers:{ 'Content-Type':'application/json' },
     body: JSON.stringify({ shape: 'Speaker' })
  });
  console.log("Target Update:", r.status, await r.text());
  
  const p = await fetch(`http://localhost:4735/measurements/${uuid}/target-settings`);
  console.log("Target GET:", await p.text());
}
test().catch(console.error);
