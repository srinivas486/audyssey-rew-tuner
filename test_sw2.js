const fs = require('fs');
async function test() {
  const ady = JSON.parse(fs.readFileSync('test.ady'));
  const sw2 = ady.detectedChannels.find(c => c.commandId === 'SW2');
  const irEntry = sw2.responseData['0'];
  let irData = Array.isArray(irEntry) ? irEntry : (irEntry.data || '');
  const floatArray = new Float32Array(irData);
  const buffer = new ArrayBuffer(floatArray.length * 4);
  const view = new DataView(buffer);
  for (let i = 0; i < floatArray.length; i++) { view.setFloat32(i * 4, floatArray[i], false); }
  const base64Data = Buffer.from(buffer).toString('base64');
  
  const res = await fetch('http://localhost:4735/import/impulse-response-data', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ identifier: 'SW2', data: base64Data, startTime: 0, sampleRate: 48000 }) });
  const importJson = await res.json();
  const uuid = importJson.uuid || importJson.id || importJson.measurement?.uuid || importJson[0]?.uuid || importJson[0]?.id || importJson.message.match(/\bID\s+(\d+)\b/i)[1];
  await new Promise(r => setTimeout(r, 1500));

  let r;
  r = await fetch('http://localhost:4735/measurements/' + uuid + '/equaliser', { method: 'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify({ manufacturer: "Generic", model: "Generic", name: "Generic" }) });
  console.log("EQ:", r.status, await r.text());

  r = await fetch('http://localhost:4735/measurements/' + uuid + '/target-settings', { method: 'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify({ type: 'Speaker', addRoomCurve: true }) });
  console.log("Target:", r.status, await r.text());

  r = await fetch('http://localhost:4735/measurements/' + uuid + '/eq/command', { method: 'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify({ command: 'Calculate target level' }) });
  console.log("Calc:", r.status, await r.text());

  const ftres = await fetch('http://localhost:4735/measurements/' + uuid + '/eq/filter-tasks', { method: 'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify({ manufacturer: 'Generic', model: 'Generic', matchRangeStart: 20, matchRangeEnd: 20000, maxMatchBoost: 3 }) });
  console.log("Filter Tasks:", ftres.status, await ftres.text());
}
test().catch(console.error);
