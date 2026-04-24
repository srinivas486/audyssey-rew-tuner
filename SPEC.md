# A1 Evo AcoustiX — Reverse Engineering Spec

> **Status:** ✅ Transfer protocol fully reverse-engineered and verified working  
> **Last updated:** 2026-04-24

## Binary Information
- **File**: `a1-evo-acoustix-linux-x64_1776918721890.` (61.7 MB)
- **Type**: pkg-compiled Node.js v18 executable
- **Version**: 3.0 (from package.json)
- **Build command**: `pkg . --targets node18-linux-x64 --output a1-evo-acoustix-linux`
- **Node entry**: `main.js`
- **Author**: OCA (avnirvana.com ecosystem)
- **License**: Personal/non-commercial use only

## Project Structure (extracted from binary)
```
a1-evo-acoustix/
├── main.js                          # Entry point
├── main.module.js                   # Main module
├── package.json                     # name: a1-evo-acoustix, version: 3.0
├── transfer_module.js              # ⚡ FILTER TRANSFER ENGINE
├── alignmentEngine.js              # Room/speaker alignment
├── impulse_response_calculator.js # IR processing
├── ir_timing.js                    # Timing calculations
├── measurement_module.js           # REW measurement integration
├── shared_utils.js                 # Shared utilities
├── subLeveling/src/
│   ├── avrClient.js                # ⚡ AVR TELNET CLIENT
│   ├── deviceController.js         # Device control
│   ├── channelMap.js              # Channel mapping
│   └── subwooferLeveling.js        # Subwoofer level/crossover
├── A1EvoAcoustiX.html              # Embedded TUI web interface
├── A1EvoCustom.html               # Custom HTML variant
├── receiver_config.avr             # Saved AVR config
├── target_curves/                  # Target curves *.txt
└── tr-curves/                      # Target reference curves *.txt
```

---

## Transfer Protocol — CONFIRMED ✅

The filter transfer uses a **binary TCP protocol on port 1256** (not Telnet port 23).

### Verified Message Types

#### 1. SET_SETDAT — Configuration (distances, trims, crossovers)
```
54 xx xx xx 08 53 45 54 5f 53 45 54 44 41 54 00 [[4 bytes meta]] [[channel]] [[SR]]
[[...config data...]]
```
- **Marker:** `0x54` (ASCII 'T')
- **Counter:** 3 bytes little-endian
- **Flag:** `0x08`
- **Command:** `SET_SETDAT` (10 bytes, padded with null)
- **Meta:** 4 bytes (purpose unknown, varies per message)
- **Channel:** 1 byte
- **SR:** 1 byte (sample rate code)
- **Config data:** variable

#### 2. SET_COEFDT — Filter Coefficients (biquad IIR coefficients)
```
54 xx xx xx 08 53 45 54 5f 43 4f 45 46 44 54 00 [[4 bytes meta]] [[channel]] [[SR]]
[[126 × float32 coefficients...]]
```
- **Length:** 531 bytes (fixed)
- **Coefficients:** 126 × float32 (LE), starting at TCP offset 22
- **Coefficient encoding:** IEEE 754 float32, **little-endian**
- **Coefficient offset:** TCP payload offset **22** (not 24)

### TCP Payload Structure (531 bytes total)
```
Byte 0:     0x54 (marker 'T')
Bytes 1-3: counter (3 bytes LE)
Byte 4:     0x08 (data transfer flag)
Bytes 5-14: 'SET_COEFDT' (10 bytes)
Byte 15:    0x00 (null padding)
Bytes 16-19: meta field (4 bytes, always 02 00 01 00 for ch0 sr0)
Byte 20:    channel number (0-10)
Byte 21:    SR code (0=32kHz, 52=44.1kHz, 57=48kHz)
Bytes 22-525: 126 float32 coefficients × 4 bytes (LE float32)
```

### SR Code Mapping
| SR Code | Sample Rate |
|---------|------------|
| 0       | 32 kHz     |
| 52      | 44.1 kHz   |
| 57      | 48 kHz     |
| 184     | 96 kHz     |

### Channel Number Mapping
| Ch | Name | Notes |
|----|------|-------|
| 0  | FL   | Front Left |
| 1  | C    | Center |
| 2  | FR   | Front Right |
| 3  | SBR  | Surround Back Right |
| 4  | SBL  | Surround Back Left |
| 5  | FHL  | Front Height Left |
| 6  | FHR  | Front Height Right |
| 7  | SW1  | Subwoofer 1 |
| 8  | SW2  | Subwoofer 2 |
| 9  | FDL  | Front Dolby Left |
| 10 | FDR  | Front Dolby Right |

### Coefficient Encoding — CONFIRMED ✅
- **Byte order:** Little-endian IEEE 754 float32
- **Offset:** TCP payload offset 22 (not 24)
- **Verification:** OCA filter[0] LE bytes found at TCP offset 22 of retransmitted blocks in pcap
  - OLD run: `9cd1fd3e` → 0.495740 (matches OCA FL filter[0])
  - NEW run: `465e023f` → 0.509251 (matches OCA FL filter[0])

### Counter Field
- 3 bytes, little-endian
- Base: `0x1300` (79488)
- Increment: `(msg_idx << 8) + channel_idx`
- Example: ch0 msg0 = 0x1300, ch1 msg0 = 0x1301, ch0 msg1 = 0x1400

---

## AVR Communication — Two Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 23   | Telnet (ASCII) | Interactive control, status queries, Audyssey on/off |
| 1256 | Raw TCP (binary) | Filter coefficient transfer, configuration |

### Telnet Commands (Port 23)
| Command | Purpose | Example |
|---------|---------|---------|
| `MSSV<ch>=<freq>Hz,<gain>dB,Q=<q>` | Set PEQ filter | `MSSVFL=63Hz,-3.5dB,Q=1.2` |
| `MSD<ch><distance_mm>` | Set distance (mm) | `MSDFL3000` |
| `MST<ch><trim_x10>` | Set trim (0.1 dB) | `MSTFL105` = +10.5 dB |
| `ZM?AUDYON` | Apply calibration | - |
| `MSSV?<ch>` | Query filter | - |

### Binary Protocol Commands (Port 1256)
| Command | Purpose |
|---------|---------|
| `GET_AVRINF` | Get AVR info (EQType, CVVer, CoefWaitTime) |
| `SET_SETDAT` | Set configuration (distances, trims, crossovers) |
| `SET_COEFDT` | Set filter coefficients (biquad IIR) |

---

## File Formats

### .oca — A1 Evo Calibration Format
```json
{
  "version": "1.0",
  "appVersion": "3.0",
  "createdAt": "2026-04-24T18:44:00.000Z",
  "model": "AVR-X3800H",
  "eqType": 2,
  "avr": { "host": "192.168.50.2", "EQType": "MultEQXT32", "CVVer": "00.01" },
  "channels": [{
    "channel": 0,
    "channelName": "FL",
    "distanceInMeters": 2.75,
    "trimAdjustmentInDbs": -0.5,
    "filter": [0.509251, -0.000547, -0.000547, ...]  // 16321 float32 BE values
  }],
  "subwoofer": { "distanceInMeters": 2.81, "trimAdjustmentInDbs": -5.0 },
  "targetCurve": "acoustix.txt"
}
```
- Coefficients stored as big-endian IEEE 754 float32 in JSON
- Convert to little-endian for SET_COEFDT transfer

### .ady — Denon MultEQ Editor Export
```json
{
  "detectedChannels": [{
    "channelName": "FL",
    "responseData": [[freq, dB], ...],
    "peqFilters": [{ "freq": 63, "gain": -3.5, "Q": 1.2, "type": "PEQ" }]
  }]
}
```

---

## Key Implementation Details

### Transfer Workflow
```
1. Connect to port 1256
2. GET_AVRINF → read CoefWaitTime (e.g., 15000 = 15s)
3. Send SET_SETDAT config messages (6 messages for full config)
4. Wait CoefWaitTime ms
5. Receive ACKs for config
6. Send SET_COEFDT coefficient messages (126 coefs per msg, all SRs)
7. Done — power cycle AVR or ZM?AUDYON to apply
```

### Biquad IIR Coefficients
The 126 coefficients per SET_COEFDT message represent **IIR biquad filter stages**:
- 126 coefficients = 21 biquad sections × 6 coefficients each, OR
- 42 PEQ filters × 3 coefficients (typical for Audyssey)

Each filter stage [b0, b1, b2, a1, a2] with a0=1 normalized.
Coefficients are transmitted as raw IIR coefficients, not PEQ parameters.

### CoefWaitTime
From `GET_AVRINF` response:
```json
{ "CoefWaitTime": { "Init": 0, "Final": 15000 } }
```
- `Final` = time to wait after sending all coefficients before applying
- For X3800H: 15000 ms (15 seconds)

---

## Rebuild Strategy

### Option A: Clean-room reimplementation (RECOMMENDED)
Use the existing `index.html` (browser SPA in this workspace) as the base:
1. Add binary TCP client for port 1256 (Node.js `net` module)
2. Implement the binary protocol parsers from this spec
3. Add `.oca` save/load for calibration storage
4. Add SSDP discovery for AVR detection
5. Integrate REW API calls for measurement/EQ matching

### Key missing pieces in existing `index.html`:
- **Binary TCP client** — no filter transfer capability
- **SSDP discovery** — AVR auto-discovery
- **Binary packet builder** — for filter transfer
- **`.oca` format support** — calibration file save/load

### Implementation order:
1. Binary TCP client (simple `net.connect` to port 1256)
2. Binary protocol parsers (SET_SETDAT, SET_COEFDT builders)
3. SSDP discovery (simple UDP multicast)
4. Command builders for MSSV/MSD/MST (Telnet port 23)
5. REW API integration improvements
6. Calibration save/load (.oca format)

---

## License Note
This spec is for **personal use only** per the binary's EULA. The author (OCA) has confirmed decompilation for personal use is acceptable.
