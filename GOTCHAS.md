# GOTCHAS.md — Lessons Learned, Traps, Known Issues

> Collected hard-won knowledge from reverse-engineering the Denon X3800H / A1 Evo AcoustiX protocol. Update this file whenever you discover a new trap.

---

## Protocol Traps

### ❗ Binary Protocol Port 1256 is Raw TCP, Not Telnet

The AVR's binary filter transfer runs on **port 1256 as raw TCP** — no Telnet negotiation, no ANSI codes, no line-ending protocol. Connecting with a Telnet client will fail or hang.

**Fix:** Use Node.js `net.connect(1256, host)` or Python `socket.socket(socket.AF_INET, socket.SOCK_STREAM)`. Do NOT use Telnet libraries for port 1256.

---

### ❗ Counter Starts at `0x1313` for AcoustiX Initial Value

The binary protocol counter field is 3 bytes little-endian. The original A1 Evo AcoustiX binary starts its counter at `0x1313` (7919 decimal), not `0x1300` as initially assumed.

**Note:** Some captures show `0x1300` as the base in early messages — the counter increments per message/channel. The exact starting value matters for AVR acceptance.

**Fix:** Capture the exact counter sequence from a known-good transfer (e.g., from `acoustix_transfer_1777065760128..pcapng`).

---

### ❗ SET_COEFDT is Fire-and-Forget — No Response Expected

Unlike SET_SETDAT (which returns an ACK), the `SET_COEFDT` coefficient transfer message is **fire-and-forget**. The AVR does not respond with any ACK or confirmation after receiving coefficients.

If you wait for a response on SET_COEFDT, your code will hang indefinitely.

**Fix:** Send the message and move on. Trust that the CoefWaitTime handles the rest.

---

### ❗ AVR Standby/Wake via POFF/PWON is NOT a Hard Power Cycle

`POFF` (standby) and `PWON` (wake) commands sent via Telnet put the AVR into a software sleep state — not a hard power cycle. The AVR maintains network connection during standby.

A true power cycle requires physical power button or hard reset. The software `POFF/PWON` cycle is sufficient to reset most DSP state but not all.

**Fix:** For full DSP reset, use `POFF` → wait 30 seconds → `PWON`. For applying new EQ without a full cycle, use `ZM?AUDYON` instead.

---

### ❗ Greeting Drain in `_connect()` Must Use Non-Blocking Recv Loop

On initial connection to the AVR's Telnet port (23), the AVR sends a greeting banner (firmware info, model name). Using `time.sleep() + recv()` to drain this causes the greeting bytes to remain in the socket buffer and corrupt the first command's response.

**Fix:** Use a **non-blocking recv loop** with `select.select()` to drain the greeting:
```python
import select, socket
sock.setblocking(False)
while True:
    r, _, _ = select.select([sock], [], [], 0.5)
    if not r:
        break
    data = sock.recv(4096)
    if not data:
        break
```

---

### ❗ SPPR Query Response Arrives in Recv Buffer But Gets Drained Prematurely

The `SPPR` (query active preset) command response arrives in the socket's recv buffer after the command is sent. However, the previous implementation's `_send()` helper was draining the buffer with a **blocking recv** that consumed the SPPR response before the caller could read it.

**Fix:** Use a **direct send + select loop** pattern for queries:
```python
sock.send(cmd + b'\r')
select.select([sock], [], [], 2.0)
response = sock.recv(4096)
```

Never wrap query sends in a helper that does a blocking recv afterward.

---

## Channel & Sample Rate Mapping

### ❗ Denon X3800H Channel Mapping (11-channel)

| Byte Value | Channel | Full Name |
|-----------|---------|-----------|
| 0 | FL | Front Left |
| 1 | C | Center |
| 2 | FR | Front Right |
| 3 | SBR | Surround Back Right |
| 4 | SBL | Surround Back Left |
| 5 | FHL | Front Height Left |
| 6 | FHR | Front Height Right |
| 7 | SW1 | Subwoofer 1 |
| 8 | SW2 | Subwoofer 2 |
| 9 | FDL | Front Dolby Left |
| 10 | FDR | Front Dolby Right |

**Note:** No dedicated Subwoofer 2 channel in the standard channel mapping — SW2 uses the same channel index space as other speakers. Verify with `GET_AVRINF` for your specific AVR configuration.

---

### ❗ CoefWaitTime from GET_AVRINF — Typically 15000ms

The `GET_AVRINF` command returns a `CoefWaitTime` field in its response. For the Denon X3800H, this is typically **15000ms** (15 seconds). This is the time to wait after sending all coefficients before the AVR applies them.

**Fix:** Always read `CoefWaitTime.Final` from the GET_AVRINF response and use it as your wait duration. Do not hardcode 15000ms — other AVR models may differ.

---

### ❗ SR Code Mapping — Not Linear

Sample rate codes in the binary protocol are **not simple integer increments**. They are scattered values:

| SR Code | Sample Rate | Notes |
|---------|-------------|-------|
| 0 | 32 kHz | Low rate |
| 52 | 44.1 kHz | CD quality |
| 57 | 48 kHz | Standard |
| 184 | 96 kHz | High resolution |

**Fix:** Use the exact code values listed above. Do not assume SR=48 means code 48.

---

## Binary Packet Structure

### ❗ Coefficient Offset is TCP Payload Offset 22 (Not 24)

The 126 filter coefficients in a SET_COEFDT message start at **TCP payload offset 22** (not 24 as initially assumed).

**Packet structure (531 bytes total):**
```
Byte 0:     0x54 ('T' marker)
Bytes 1-3:  counter (3 bytes LE)
Byte 4:     0x08 (data transfer flag)
Bytes 5-14: 'SET_COEFDT' (10 bytes)
Byte 15:    0x00 (null padding)
Bytes 16-19: meta field (4 bytes) — always 02 00 01 00 for coefficients
Byte 20:    channel number (0-10)
Byte 21:    SR code (0=32kHz, 52=44.1kHz, 57=48kHz, 184=96kHz)
Bytes 22-525: 126 × float32 coefficients (LE IEEE 754)
```

**Fix:** When building binary packets, write channel at offset 20, SR at offset 21, then coefficients starting at offset 22.

---

### ❗ Float Encoding — IEEE 754 Little-Endian

All filter coefficients are transmitted as **little-endian IEEE 754 float32**. This is different from the `.oca` JSON format which stores coefficients as big-endian strings.

**Verification (from pcap):**
- OCA filter[0] (FL): `9cd1fd3e` → 0.495740 (LE) or `3efd19c` → 0.246870 (BE)
- Capture confirmed `9cd1fd3e` at TCP offset 22 in retransmitted blocks

**Fix:** When sending coefficients, pack as `<f` (little-endian float) in Python struct, or `Buffer.from([...], 'le')` in Node.js.

---

## Other Gotchas

### ❗ Power Cycle Warning Required Before AVR Reset

When performing a power cycle on the Denon X3800H, there is a risk that the AVR loses power while data is still being written to internal memory. This can corrupt the Audyssey calibration data.

**Fix:** Always display a warning to the user before initiating a power cycle: "This will reset the AVR. Make sure no data transfer is in progress."

---

### ❗ OCA File is Big-Endian; Binary Protocol is Little-Endian

The `.oca` calibration files store filter coefficients as **big-endian** IEEE 754 float32 encoded as hex strings in JSON. The binary protocol on port 1256 requires **little-endian**.

**Fix:** When reading from `.oca` and sending via SET_COEFDT:
```python
import struct
be_bytes = bytes.fromhex(oca_filter_value)  # e.g. '3efd19c'
be_float = struct.unpack('>f', be_bytes)[0]  # big-endian
le_bytes = struct.pack('<f', be_float)       # little-endian
```

---

### ❗ Telnet IAC Negotiation on Port 23

The AVR's Telnet service on port 23 will send IAC (0xFF) negotiation codes on connection. If not handled, these bytes corrupt the first command response.

**Fix:** Set socket to binary mode or explicitly respond to IAC commands. Simpler: use `setblocking(False)` + `select.select()` to drain negotiation noise before sending commands.

---

### ❗ Binary Protocol Requires Same SR for All Channels

When transferring coefficients, all messages for a given sample rate must be sent before moving to the next SR. The AVR processes coefficients per SR slot — mixing SRs across channels mid-batch will cause incorrect filter application.

**Fix:** Send all channels for SR=0 first, then all channels for SR=52, etc. Never mix SR values within a batch.

---

### ❗ CoefWaitTime Applies Per-SR Block

The `CoefWaitTime` from GET_AVRINF applies per SR block — wait after sending all channels for one sample rate, then send the next SR block. Some AVR models require waiting between each SR block.

**Fix:** For each SR (0, 52, 57, 184):
1. Send all 11 channels' SET_COEFDT for this SR
2. Wait `CoefWaitTime.Final` ms
3. Continue to next SR

---

*Last updated: 2026-04-26*