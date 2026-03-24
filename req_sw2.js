async function test() {
  const mRes = await fetch('http://localhost:4735/measurements');
  const mList = await mRes.json();
  const keys = Object.keys(mList);
  const uuid = mList[keys[keys.length-1]].uuid;
  console.log("UUID:", uuid);
  
  const p = await fetch(`http://localhost:4735/measurements/${uuid}/frequency-response`);
  console.log("Freq Resp:", p.status, await p.text());
}
test().catch(console);
