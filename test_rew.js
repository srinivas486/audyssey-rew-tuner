const fs = require('fs');
async function test() {
  const ady = JSON.parse(fs.readFileSync('test.ady'));
  const ch = ady.detectedChannels[0];
  const irEntry = ch.responseData['0'];
  let irData = Array.isArray(irEntry) ? irEntry : (irEntry.data || '');
  const floatArray = new Float32Array(irData);
  const base64Data = Buffer.from(floatArray.buffer).toString('base64');
  console.log("Sending to REW...");
  const res = await fetch('http://localhost:4735/import/impulse-response-data', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      identifier: ch.commandId,
      data: base64Data,
      startTime: 0,
      sampleRate: 48000
    })
  });
  const text = await res.text();
  console.log("Import result:", res.status, text);
  const res2 = await fetch('http://localhost:4735/measurements');
  const text2 = await res2.text();
  console.log("Measurements:", text2.substring(0, 200));
}
test().catch(console.error);
