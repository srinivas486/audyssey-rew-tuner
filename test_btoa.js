const fs = require('fs');

function floatArrayToBase64(floatArray) {
  const buffer = floatArray.buffer;
  let binary = '';
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

async function test() {
  const ady = JSON.parse(fs.readFileSync('test.ady'));
  const ch = ady.detectedChannels[0];
  const irEntry = ch.responseData['0'];
  let irData = Array.isArray(irEntry) ? irEntry : (irEntry.data || '');
  
  const floatArray = new Float32Array(irData);
  
  // Use the browser-mimicked base64 function
  const base64Data = floatArrayToBase64(floatArray);

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

  // Add 1s delay
  await new Promise(r => setTimeout(r, 1000));

  const res2 = await fetch('http://localhost:4735/measurements');
  const text2 = await res2.text();
  const meas = JSON.parse(text2 || "{}");
  console.log("Measurements count:", Object.keys(meas).length);
}
test().catch(console.error);
