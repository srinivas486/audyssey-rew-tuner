# OCA Filter Coefficient Transfer Fix — Planner Analysis

**Date:** 2026-04-28  
**Project:** Audyssey REW Tuner — `feature/audyssey-rew-tuner` branch  
**Status:** Root cause identified

---

## 1. Documents Found and Read

| Document | Location | Key Info |
|----------|----------|----------|
| `SPEC.md` | `/root/.openclaw/workspace/audyssey-rew-tuner/SPEC.md` | Full binary protocol spec — SET_SETDAT, SET_COEFDT, port 1256 |
| `transfer.js` | `/root/.openclaw/workspace/audyssey-rew-tuner/transfer.js` | Main Node.js transfer implementation (~3500 lines) |
| `oca_transfer.py` | `/root/.openclaw/workspace/audyssey-rew-tuner/oca_transfer.py` | Working Python transfer (verified working Apr 24) |
| `rew_to_audyssey.py` | `/root/.openclaw/workspace/audyssey-rew-tuner/rew_to_audyssey.py` | REW-to-AVR PEQ writer |
| `GOTCHAS.md` | `/root/.openclaw/workspace/audyssey-rew-tuner/GOTCHAS.md` | Known traps including SET_COEFDT fire-and-forget |
| `PLAN.md` | `/root/.openclaw/workspace/audyssey-rew-tuner/PLAN.md` | Epic 1 story list |
| `CHANGELOG.md` | `/root/.openclaw/workspace/audyssey-rew-tuner/CHANGELOG.md` | History of transfer success on Apr 24 |
| `avr_telnet.py` | `/root/.openclaw/workspace/tools/denon-x3800h/avr_telnet.py` | Python Telnet AVR control |

**Note:** No Apr 27 memory files found. Vasu's transfer notes appear to be in-session. The only external reference to the calibration state machine is in GOTCHAS.md and the `oca_transfer.py` working implementation itself.

---

## 2. Root Cause Analysis

### The Hypothesis
> "Audy Cal Mode" must be set ON before sending filter coefficients, then the coefficients sent, then finalized, then exit "Audy Cal Mode."

### What the Working Implementation Actually Does (`oca_transfer.py`)

The **verified-working** `oca_transfer.py` (Apr 24, confirmed successful transfer) uses **no calibration mode commands at all**:

```
CONNECT port 1256
  ↓
GET_AVRINF  → read CoefWaitTime
  ↓
SET_SETDAT  → send config (distances, trims) — fire-and-forget, collect ACKs at end
  ↓
SET_COEFDT  → send coefficients — pure fire-and-forget, no ACK, no INIT_COEFS, no FINZ_COEFS, no AudyFinFlg=Fin, no EXIT_AUDMD
  ↓
DISCONNECT
  ↓
Power cycle or ZM?AUDYON to apply
```

### What `transfer.js` Does (BROKEN)

```javascript
CONNECT port 1256
  ↓
GET_AVRINF  → read CoefWaitTime, dataType
  ↓
ENTER_AUDY  → hex: 5400130000454e5445525f4155445900000077  ← EXTRA
  ↓
SET_SETDAT  → send config per channel
  ↓
if (dataType === 'fixed') {
  INIT_COEFS  → hex: 5400130000494e49545f434f4546530000006a  ← EXTRA
}
  ↓
SET_COEFDT  → send coefficients
  ↓
FINZ_COEFS  → hex: 540013000046494e5a5f434f4546530000006d  ← EXTRA
  ↓
SET_SETDAT (AudyFinFlg=Fin)  ← EXTRA
  ↓
EXIT_AUDMD  → hex: 5400130000455849545f4155444d440000006b  ← EXTRA
  ↓
DISCONNECT
```

---

## 3. Critical Bug: SET_COEFDT Expects ACK But Is Fire-and-Forget

### Bug Location
`transfer.js`, line ~3109:
```javascript
await sendFunction(packetBufferToSend, packetLabel, {
    expectAck: true,        // ← BUG: should be false
    addChecksum: false,
    timeout: TRANSFER_CONFIG.timeouts.command  // 5000ms
});
```

### Evidence from GOTCHAS.md
> **SET_COEFDT is Fire-and-Forget — No Response Expected**
> The AVR does not respond with any ACK or confirmation after receiving coefficients. If you wait for a response on SET_COEFDT, your code will hang indefinitely.

### Impact
- `expectAck: true` with 5-second timeout per packet
- 220+ coefficient packets × 5 seconds = **1100+ seconds** (18+ minutes)
- Transfer never completes within CoefWaitTime window
- Coefficients silently fail to transfer

### What `oca_transfer.py` Does Correctly
```python
for i, msg in enumerate(coef_msgs):
    sock.send(msg)
    time.sleep(0.02)  # fire-and-forget, no ACK wait
```

---

## 4. Secondary Issue: Extra Calibration Commands

The following commands in `transfer.js` are **NOT used by the working implementation** and may be interfering with the transfer:

| Command | Hex | Used by oca_transfer.py? | Purpose |
|---------|-----|-------------------------|---------|
| `ENTER_AUDY` | `5400130000454e5445525f4155445900000077` | ❌ NO | Enter calibration mode |
| `INIT_COEFS` | `5400130000494e49545f434f4546530000006a` | ❌ NO | Initialize coefficients |
| `FINZ_COEFS` | `540013000046494e5a5f434f4546530000006d` | ❌ NO | Finalize coefficients |
| `EXIT_AUDMD` | `5400130000455849545f4155444d440000006b` | ❌ NO | Exit calibration mode |
| `SET_SETDAT (AudyFinFlg=Fin)` | via buildAvrPacket | ❌ NO | Final flag |

**Hypothesis:** `ENTER_AUDY` may put the AVR in a state where it expects a different transfer protocol (INIT_COEFS → COEFS → FINZ_COEFS → EXIT_AUDMD sequence), but the code then sends SET_COEFDT using the non-calibration-mode packet format, causing the AVR to reject/nack the packets.

---

## 5. Packet Format Comparison

### `oca_transfer.py` Simple Format (Working)
```
54 [counter:3] 08 'SET_COEFDT' 00 [meta:4] [ch] [sr] [coefs:504] → checksum
Total: 1+3+1+10+1+4+1+1+504+1 = 527 bytes → actually 531 per spec
```

### `transfer.js` Complex Format (Broken)
```javascript
// generatePacketsForTransfer() builds:
54 [length:2] [packetIdx] [lastSeq] [SET_COEFDT header + size field] [params+data] [checksum]
// Uses per-packet ACKing instead of fire-and-forget
```

### Required Fix
Replace the `generatePacketsForTransfer` packet structure with the simple flat format from `oca_transfer.py`:
```javascript
Buffer.concat([
    Buffer.from([MARKER]),
    counterBuffer,           // 3 bytes LE
    Buffer.from([FLAG_SET_COEF]),  // 0x08
    Buffer.from('SET_COEFDT'),
    Buffer.from([0x00]),
    META_COEF,               // Buffer.from([0x02, 0x00, 0x01, 0x00])
    Buffer.from([channel, srCode]),
    coefBuffer               // 504 bytes (126 floats × 4)
]);
```

---

## 6. Data Type Handling — Reference Curve Bug

`transfer.js` sends **two** target curves:
```javascript
for (const tc of TRANSFER_CONFIG.targetCurves) {  // ['00', '01']
    const curveName = tc === '01' ? 'Reference' : 'Flat';
    // ...
    const coeffsToSend = (tc === '01') ? processedDataForChannel.filterLV : processedDataForChannel.filter;
```

If the OCA file has no `filterLV` data (Reference/Legacy Vintage), all Reference curve transfers are skipped with a warning. This may be intended behavior but could confuse users expecting Reference curve support.

---

## 7. Fix Plan for Developer

### Phase 1: Fix Coefficient Packet Fire-and-Forget (Critical)
**File:** `transfer.js`, function `sendCoeffsForAllSampleRates` (~line 3109)

Change each coefficient packet send from:
```javascript
await sendFunction(packetBufferToSend, packetLabel, {
    expectAck: true,         // WRONG
    addChecksum: false,
    timeout: TRANSFER_CONFIG.timeouts.command
});
```

To fire-and-forget:
```javascript
client.write(packetBufferToSend);  // no await, no ACK
await delay(20);  // inter-packet delay (like oca_transfer.py's 20ms)
```

OR create a proper fire-and-forget sender:
```javascript
async function sendFireAndForget(socket, buffer) {
    return new Promise((resolve) => {
        socket.write(buffer, () => resolve());
    });
}
```

### Phase 2: Align Packet Format with Working Implementation
**File:** `transfer.js`, function `generatePacketsForTransfer` (~line 2660)

Replace complex packet structure with the simple flat format from `oca_transfer.py`. Keep the same counter logic and coefficient ordering.

### Phase 3: Remove Extraneous Calibration Commands (Optional but Recommended)
**File:** `transfer.js`, function `runCalibrationTransfer` (~line 2934)

Remove or make optional:
- `ENTER_AUDY` — NOT used by working implementation
- `INIT_COEFS` — NOT used by working implementation
- `FINZ_COEFS` — NOT used by working implementation  
- `SET_SETDAT (AudyFinFlg=Fin)` — NOT used by working implementation
- `EXIT_AUDMD` — NOT used by working implementation

**Rationale:** `oca_transfer.py` achieves successful transfer without any of these. They may have been added based on incorrect assumptions about the protocol.

### Phase 4: Add Debug Instrumentation
Add hex dump logging before each packet send:
```javascript
console.log(`[COEF SEND] ${packetLabel} | ${packetBufferToSend.slice(0, 24).toString('hex')}...`);
```

Add timing instrumentation:
```javascript
const sendStart = Date.now();
for (const packet of packets) {
    socket.write(packet.bufferData);
    await delay(20);
}
console.log(`[COEF TIMING] ${packets.length} packets sent in ${Date.now() - sendStart}ms`);
```

### Phase 5: Verify with Working Implementation
Before declaring fix complete, compare packet-level output of `transfer.js` against `oca_transfer.py` for the same OCA file using identical coefficient values. Both should produce byte-identical SET_COEFDT packets.

---

## 8. Testing Strategy

1. **Unit test:** Use the same OCA file in both `transfer.js` and `oca_transfer.py`. Log the hex of every SET_COEFDT packet from both. They must match byte-for-byte for the same coefficients.
2. **Integration test:** Run `transfer.js` with a test OCA file, verify no timeouts occur during coefficient phase.
3. **End-to-end test:** Transfer to AVR, power cycle, verify filter coefficients are active by querying `MSSV?<ch>` via Telnet or comparing pre/post REW measurements.

---

## 9. SPEC.md Update Required

After fixing, update `SPEC.md` to:
1. Document that `ENTER_AUDY`, `INIT_COEFS`, `FINZ_COEFS`, `EXIT_AUDMD` are NOT required for OCA transfer
2. Confirm `SET_COEFDT` is pure fire-and-forget with 20ms inter-packet delay
3. Add the simple flat packet format as the canonical format (remove complex multi-stage description)
4. Note that `oca_transfer.py` is the reference implementation
