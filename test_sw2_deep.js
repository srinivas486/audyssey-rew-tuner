const fs = require('fs');

async function rewAPI(method, path, body) {
  const params = { method: method, headers: { 'Content-Type': 'application/json' } };
  if (body) params.body = JSON.stringify(body);
  const res = await fetch('http://localhost:4735' + path, params);
  const text = await res.text();
  console.log(`${method} ${path} -> ${res.status} ${text}`);
  return { status: res.status, text };
}

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
  
  console.log("--> IMPORT SW2");
  await rewAPI('POST', '/import/impulse-response-data', { identifier: 'SW2', data: base64Data, startTime: 0, sampleRate: 48000 });
  
  await new Promise(r => setTimeout(r, 1500));
  
  console.log("--> FETCH M");
  const mRes = await fetch('http://localhost:4735/measurements');
  const mList = await mRes.json();
  const keys = Object.keys(mList);
  const uuid = mList[keys[keys.length-1]].uuid;
  console.log("UUID:", uuid);
  
  console.log("--> EQUALISER");
  await rewAPI('POST', `/measurements/${uuid}/equaliser`, { manufacturer: "Generic", model: "Generic" });
  
  console.log("--> TARGET SETTINGS");
  await rewAPI('POST', `/measurements/${uuid}/target-settings`, { type: 'Speaker', addRoomCurve: true });
  
  console.log("--> CALCULATE TARGET");
  await rewAPI('POST', `/measurements/${uuid}/eq/command`, { command: 'Calculate target level' });
  
  console.log("--> FILTER TASKS");
  await rewAPI('POST', `/measurements/${uuid}/eq/filter-tasks`, {
    manufacturer: 'Generic', model: 'Generic', matchRangeStart: 20, matchRangeEnd: 250, maxMatchBoost: 3, maxOverallBoost: 3, individualMaxBoost: 3
  });
}
test().catch(console.error);
