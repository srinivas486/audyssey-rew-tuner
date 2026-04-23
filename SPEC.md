# A1 Evo AcoustiX — Reverse Engineering Spec

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
├── main.js
├── transfer_module.js              # ⚡ FILTER TRANSFER ENGINE
├── alignmentEngine.js              # Room/speaker alignment
├── impulse_response_calculator.js   # IR processing
├── ir_timing.js                    # Timing calculations  
├── measurement_module.js           # REW measurement integration
├── shared_utils.js                 # Shared utilities
├── subLeveling/src/
│   ├── avrClient.js                # ⚡ AVR TELNET CLIENT
│   ├── deviceController.js        # Device control
│   ├── channelMap.js              # Channel mapping
│   └── subwooferLeveling.js       # Subwoofer level/crossover
├── A1EvoAcoustiX.html             # Embedded TUI web interface
├── A1EvoCustom.html               # Custom HTML variant
├── receiver_config.avr            # Saved AVR config
├── target_curves/                  # Target curves *.txt
└── tr-curves/                      # Target reference curves *.txt
```

## Architecture

### AVR Discovery — SSDP (UDP Multicast)
- **Address**: `239.255.255.250:1900`
- **ST Header**: `urn:schemas-denon-com:device:ACT-DenonDeviceService:1`
- **Implemented by**: `UPNPDiscovery` class → `getAvrInfoAndStatusForConfig`

### AVR Communication — Raw Telnet (Port 23)
- **Functions**: `sendTelnetCommands`, `_connectToAVR`, `AvrClient`
- **Control port**: 23 (Telnet, raw TCP)
- **Commands**: `MSSV`, `MSD`, `MST`, `MSQ` + zone commands `ZEM`, `ZEO`, `ZEA`, etc.

### REW Integration (HTTP REST API — Port 4735)
- **Base URL**: `http://127.0.0.1:4735/`
- **Endpoints used**:
  - `POST /eq/import-impulse` — Import IR data (base64 Big-Endian IEEE 754 float32)
  - `POST /eq/filter` — Configure filter tasks
  - `POST /eq/match-target` — Match target curve
  - `GET /measurements/curve` — Get resulting curve data
  - `GET /eq/house-curve` — House curve
  - `POST /eq/export-raw` — Export filter coefficients
- **IR Format**: base64-encoded Big-Endian IEEE 754 float32, `sampleRate: 48000`

### Filter Transfer Protocol — Binary over Telnet
The binary protocol uses `sendSetDatCommand` → `buildPacketConfig` → `channelByteTable` mapping.

**Key functions** (in order of call):
1. `validateConfigurationAndPrompt`
2. `prepareParamsInOrder`
3. `sendSetDatCommand`
4. `processFilterDataForTransfer`
5. `generatePacketsForTransfer`
6. `buildPacketConfig` → `buildAvrPacket` → `hexWithChecksum`
7. `finalizeTransfer`
8. `sendCoeffsForAllSampleRates`

**Binary format** (deduced from function names and string table):
- `hexWithChecksum` — builds AVR command packets
- `channelByteTable` — maps channels to type bytes (FL/FR/C/etc.)
- `getChannelTypeByte` — gets byte value for channel type
- `javaFloatToFixed32bits` / `floatToBufferLE` — converts floats to fixed 32-bit LE
- `fixed32IntToBufferLE` — writes integers to buffer little-endian

**Key constants**:
- `AVR_CONTROL_PORT` — port 23 (Telnet)
- `MEASUREMENT_CHANNEL_ORDER_FIXEDA` — channel ordering constant
- `HEIGHT_SPEAKERS` — height speaker config
- `hasHeightSpeakers` — detection flag

## Telnet Command Protocol (Denon/Marantz)

### Commands (from string table analysis):
| Command | Purpose |
|---------|---------|
| `MSSV<ch>=<freq>Hz,<gain>dB,Q=<q>` | Set PEQ filter |
| `MSD<ch><distance_mm>` | Set distance (in mm) |
| `MST<ch><trim_x10>` | Set trim (in 0.1 dB) |
| `MSQ<ch><filter_num>` | Query filter |
| `MFGA` | Group A config |
| `MNGT` | Management |
| `PWST` | Power status |
| `CV`, `PV`, `PS`, `SM`, `SI` | Volume/display modes |

### Zone Commands:
| Command | Purpose |
|---------|---------|
| `ZEM` | Zone enter mode |
| `ZEO` | Zone enter on |
| `ZEA` | Zone enter all |

### Channels (from channel map):
`FL`, `FR`, `C`, `SW` (subwoofer), `SL`, `SR`, `BL`, `BR`, `SBL`, `SBR`  
Plus height channels when `hasHeightSpeakers` is true.

## Express API Server (Port 3000)

Embedded HTTP server for the browser UI. Endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/get-app-path` | Get app base path |
| `GET /api/get-curve-data` | Get measurement curve |
| `GET /api/get-mic-calibration` | Get mic calibration data |
| `GET /api/get-target-curves` | Get target curves |
| `GET /api/get-tr-curve-data` | Get target reference curve |
| `POST /api/set-house-curve` | Set house curve in REW |
| `POST /api/align` | Run alignment |
| `POST /api/find-sub-ir-start` | Find subwoofer IR start |
| `POST /api/calculate-shift` | Calculate IR shift |
| `POST /api/save-oca` | Save .oca calibration |

## File Formats

### .ady — Denon MultEQ Editor Export
JSON format from Denon "MultEQ Editor" app:
```json
{
  "detectedChannels": [{
    "channelName": "FL",
    "responseData": [/* frequency response array */],
    "peqFilters": [/* PEQ filter definitions */]
  }],
  "channelReport": {/* channel measurement report */},
  "micCalibration": {/* microphone calibration data */}
}
```

### .oca — A1 Evo Calibration Format
JSON format specific to A1 Evo:
```json
{
  "version": "1.0",
  "appVersion": "3.0",
  "createdAt": "<ISO timestamp>",
  "avr": {/* AVR info */},
  "channels": [/* per-channel filter data */],
  "subwoofer": {/* subwoofer config */},
  "targetCurve": {/* target curve */},
  "ocaData": {/* full calibration data */}
}
```

## Key Implementation Details

### Transfer Module (`transfer_module.js`)
The transfer module handles the full filter transfer workflow:
- Sends filter coefficients in multiple sample rates
- Uses binary packet format with channel-byte mapping
- Implements retry logic (`sendWithRetries`)
- Reports progress via `TransferProgress` interface

### Telnet Client (`subLeveling/src/avrClient.js`)
- Raw TCP socket connection to AVR port 23
- `hexWithChecksum` command building
- `commandTimeout` for timeout handling
- `commandTimer` for timing
- Response parsing via `_sendRawAndParseJsonHelper_Robust`

### Binary Protocol Flow
```
User Input → validateConfigurationAndPrompt
  → prepareParamsInOrder (sort channels)
  → sendSetDatCommand
    → processFilterDataForTransfer
      → generatePacketsForTransfer
        → buildPacketConfig (per packet)
          → buildAvrPacket (per channel)
            → getChannelTypeByte (from channelByteTable)
            → javaFloatToFixed32bits (coefficient encoding)
            → hexWithChecksum (packet framing + checksum)
    → socket.write(packet)
  → finalizeTransfer
  → sendCoeffsForAllSampleRates (multi-rate transfer)
```

## Rebuild Strategy

Since the binary is pkg-compiled and the source cannot be legally reproduced identically:

### Option A: Clean-room reimplementation (RECOMMENDED)
Use the existing `index.html` (browser SPA in this workspace) as the base:
1. Add Telnet AVR client using raw TCP sockets (Node.js `net` module)
2. Implement the `MSxxxx` command protocol documented above
3. Add `.oca` save/load for calibration storage
4. Integrate REW API calls (already have this part)
5. Add SSDP discovery for AVR detection

### Key missing pieces in existing `index.html`:
- **Telnet client** — no AVR upload capability currently
- **SSDP discovery** — AVR auto-discovery
- **Binary packet builder** — for filter transfer
- **`.oca` format support** — calibration file save/load

### Implementation order:
1. Telnet client (simple `net.connect` to port 23)
2. SSDP discovery (simple UDP multicast)
3. Command builders for MSSV/MSD/MST
4. REW API integration improvements
5. Calibration save/load (.oca format)

## Data Structures

### ChannelByteTable (from binary string table)
Maps channel names to type bytes for the binary protocol:
- `FL` → 0x01 (or similar)
- `FR` → 0x02
- `C` → 0x03
- `SW` → 0x04
- etc.

### TransferProgress Interface
```typescript
interface TransferProgress {
  totalChannels: number;
  totalCurves: number;
  totalSampleRates: number;
  totalOps: number;
  completedOps: number;
  currentChannel: number;
  currentCurve: number;
  currentSR: number;
  currentPkt: number;
  totalPkts: number;
  coefficients: Float32Array;
  phase: string;
  startTime: number;
  phaseStartTime: number;
  totalPacketsSent: number;
  statusMsg: string;
}
```

## Known Constants
- `SERVER_PORT`: 3000
- `AVR_CONTROL_PORT`: 23 (Telnet)
- `REW_API_PORT`: 4735
- `commandTimeout`: ~5000ms
- `bufferLimitBytes`: 4096
- Sample rate labels (`SR_LABELS`): 48kHz, 96kHz, etc.

## License Note
This spec is for **personal use only** per the binary's EULA. The author (OCA) has confirmed decompilation for personal use is acceptable.
