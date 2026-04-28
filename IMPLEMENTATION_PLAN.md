# A1 Evo AcoustiX — Echo Console Implementation Plan

## Overview

Build a complete functional clone of A1 Evo AcoustiX as a new **tab/section** in the Echo Console at `/root/.openclaw/workspace/home-console/`.

**Architecture:**
```
Browser → Echo Console (port 18790) → REW API (localhost:4735)   [already works]
Browser → Echo Console (port 18790) → Raw Telnet to AVR (port 23)  [needs building]
```

The Echo Console already serves the Audyssey REW Tuner SPA (`/root/.openclaw/workspace/audyssey-rew-tuner/index.html`). The A1 Evo AcoustiX clone will be integrated as a **new tab** in the same SPA, sharing the same server-side infrastructure.

---

## Reference Files

| File | Purpose |
|------|---------|
| `SPEC.md` | Full protocol details — SSDP, Telnet, REW API, file formats |
| `A1EvoAcoustiX_embedded.html` | UI/UX reference (1166 lines) — layout, controls, charts |
| `index.html` (existing) | Existing Audyssey page — REW API + ADY parsing + PEQ math (2609 lines) |
| `server.js` | Echo Console server (1419 lines) — auth, routing, SSH polling patterns |

---

## Architecture Decisions

### 1. Frontend: New Tab in Existing SPA

The existing Audyssey REW Tuner SPA (`index.html` at `/root/.openclaw/workspace/audyssey-rew-tuner/`) is served by the Echo Console via a proxy route. We add a **second tab** to the SPA for the A1 Evo interface.

**Why not a separate page?**
- Share existing REW API proxy infrastructure
- Share auth/session layer
- Share Chart.js and UI component library

**UI Layout** (from `A1EvoAcoustiX_embedded.html`):
```
┌─────────────────────────────────────────────────────┐
│ A1 Evo AcoustiX                        [Support][×] │
├─────────────────┬──────────────────┬─────────────────┤
│ TARGET RESPONSE │ BASS MANAGEMENT │ INTERACTIVE     │
│ • Target Curve  │ • Subwoofer     │ • Volume Level  │
│ • Crossover     │ • Double Bass   │ • Manual Align  │
│   Freq Range    │ • MIMO Process  │ • Custom Filter│
│ • Max EQ Freq   │ • Sub Eq Range  │ • Low Vol Comp  │
│                 │ • LPF for LFE   │ • Tactile Trans│
│                 │ • Filter Boost  │                │
│                 │ • THX Mode      │                │
└─────────────────┴─────────────────┴─────────────────┘
│           [ START OPTIMIZATION ]                   │
```

**Color/Theme tokens** (from embedded HTML):
- Primary: `#ffb300` (amber/gold)
- Background: `#212121` → `#1a1a1a`
- Card bg: `#263238`
- Panel bg: `#1c2429`
- Text: `#eceff1`

### 2. Server: New Module `a1-evo-server.js`

New server-side module at `/root/.openclaw/workspace/home-console/a1-evo-server.js` — handles:
- SSDP AVR discovery (Node.js `dgram` multicast)
- Telnet AVR client (Node.js `net` module)
- REW API proxy (already partially exists, extend it)
- `.oca` calibration save/load
- `.ady` MultEQ Editor import

**Integration into `server.js`:**
```javascript
// In server.js — mount the A1 Evo router
const a1Evo = require('./a1-evo-server');
server.on('request', (req, res) => {
  // ... existing routes first ...
  // Then A1 Evo routes (prefix: /api/a1evo/*)
  a1Evo.handle(req, res);
});
```

### 3. SSR/Backend Communication

All A1 Evo features require server-side code:
- **SSDP Discovery** — must be done server-side (Node.js `dgram`)
- **Telnet AVR Control** — must be done server-side (Node.js `net`)
- **REW API calls** — server proxies to `localhost:4735`
- **File access** — `.oca`/`.ady` files stored on CIFS NAS

---

## New Server Routes

### SSR Proxy Routes

| Route | Method | Purpose | Implementation |
|-------|--------|---------|----------------|
| `/api/a1evo/discover` | POST | SSDP multicast discovery of AVRs | `a1-evo-server.js` → `dgram` |
| `/api/a1evo/connect` | POST | Connect Telnet to AVR, return status | `net.connect` to port 23 |
| `/api/a1evo/disconnect` | POST | Close Telnet connection | destroy socket |
| `/api/a1evo/send-command` | POST | Send raw command to AVR | Telnet write |
| `/api/a1evo/send-peq` | POST | Send PEQ filters (MSSV) | Telnet write, batch |
| `/api/a1evo/set-distance` | POST | Set speaker distance (MSD) | Telnet write, batch |
| `/api/a1evo/set-trim` | POST | Set channel trim (MST) | Telnet write, batch |
| `/api/a1evo/transfer-filters` | POST | Full filter transfer (binary protocol) | Transfer module |
| `/api/a1evo/rew-import-ir` | POST | Import IR to REW | proxy to REW API |
| `/api/a1evo/rew-match-target` | POST | Generate PEQ matching target curve | proxy to REW API |
| `/api/a1evo/rew-get-curve` | GET | Get measurement curve from REW | proxy to REW API |
| `/api/a1evo/rew-house-curve` | POST | Set house curve in REW | proxy to REW API |
| `/api/a1evo/parse-ady` | POST | Parse .ady MultEQ Editor file | JSON parse + normalize |
| `/api/a1evo/save-oca` | POST | Save calibration as .oca | write to CIFS |
| `/api/a1evo/load-oca` | GET | Load calibration from .oca | read from CIFS |
| `/api/a1evo/target-curves` | GET | List available target curves | file system |

---

## Data Structures

### AVR Telnet State (in-memory, server-side)
```javascript
{
  host: '192.168.1.XX',
  port: 23,
  model: 'Denon AVR-X3800H',
  hasHeightSpeakers: true,
  connected: false,
  socket: net.Socket | null
}
```

### PEQ Filter (per channel)
```javascript
{
  channel: 'FL',        // FL, FR, C, SW, SL, SR, BL, BR, SBL, SBR, FD, FS, TM, RL, RR
  filters: [
    { freq: 63, gain: -3.5, q: 1.2 },
    { freq: 100, gain: 2.0, q: 2.0 },
    // ... up to 6+ filters
  ]
}
```

### Calibration (.oca) Format
```javascript
{
  version: '1.0',
  appVersion: '3.0',
  createdAt: '2026-04-23T...',
  avr: { host, model, hasHeightSpeakers },
  channels: [{ channel, distance_mm, trim_x10, filters: [] }],
  targetCurve: 'acoustix.txt',
  // ... full state from A1 Evo settings panel
}
```

### ADY (.ady) Import Format (from Denon MultEQ Editor)
```javascript
{
  detectedChannels: [{
    channelName: 'FL',
    responseData: [[freq, dB], ...],   // frequency response pairs
    peqFilters: [{ freq, gain, q }, ...]
  }],
  channelReport: {},
  micCalibration: {}
}
```

---

## Step-by-Step Implementation Order

### Phase 1: Server Infrastructure (foundational)

#### Step 1.1 — Create `a1-evo-server.js` module
**File:** `/root/.openclaw/workspace/home-console/a1-evo-server.js`

Skeleton with:
- Route handler function `handle(req, res)` — mounts on `/api/a1evo/*`
- `AVRClient` class wrapping `net.Socket`
- `SSDPDiscovery` class wrapping `dgram`
- Connection state management

#### Step 1.2 — SSDP AVR Discovery
**Implementation:**
```javascript
// Send UDP multicast:
const message = Buffer.from(
  'M-SEARCH * HTTP/1.1\r\n' +
  'HOST: 239.255.255.250:1900\r\n' +
  'MAN: "ssdp:discover"\r\n' +
  'MX: 3\r\n' +
  'ST: urn:schemas-denon-com:device:ACT-DenonDeviceService:1\r\n' +
  '\r\n'
);
sock.send(message, 0, message.length, 1900, '239.255.255.250');
```

Parse SSDP responses for `LOCATION:` header → fetch device XML → extract `modelName`, `serialNumber`, AVR IP.

**Route:** `POST /api/a1evo/discover` → returns list of discovered AVRs

#### Step 1.3 — Telnet AVR Client
**Implementation:**
```javascript
const net = require('net');
const client = net.connect(23, avrHost);
// Handle telnet negotiation (IAC commands)
// Send: `MSSVFL=63Hz,-3.5dB,Q=1.2\r`
// Parse response
```

**Key commands (from SPEC.md):**
| Command | Format | Purpose |
|---------|--------|---------|
| Set PEQ | `MSSV<ch>=<freq>Hz,<gain>dB,Q=<q>` | Set filter (e.g. `MSSVFL=63Hz,-3.5dB,Q=1.2`) |
| Set Distance | `MSD<ch><distance_mm>` | Set distance in mm (e.g. `MSDFL3000`) |
| Set Trim | `MST<ch><trim_x10>` | Set trim in 0.1 dB (e.g. `MSTFL105` = +10.5 dB) |

**Route:** `POST /api/a1evo/connect` → `POST /api/a1evo/disconnect` → `POST /api/a1evo/send-command`

### Phase 2: REW API Proxy (extend existing)

The Echo Console doesn't currently proxy REW API calls. The existing `index.html` (audyssey-rew-tuner) has client-side REW integration. We move this server-side.

#### Step 2.1 — REW API routes in `a1-evo-server.js`
```javascript
const REW_API = 'http://127.0.0.1:4735';

// POST /api/a1evo/rew-import-ir
// body: { channel: 'FL', irData: base64Float32, sampleRate: 48000 }
async function importIR(channel, irData, sampleRate) {
  const res = await fetch(`${REW_API}/eq/import-impulse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ channel, irData, sampleRate })
  });
  return res.json();
}

// POST /api/a1evo/rew-match-target
// body: { channel: 'FL', targetCurve: [...freq/boost pairs] }
async function matchTarget(channel, targetCurve) { ... }

// GET /api/a1evo/rew-get-curve?channel=FL
async function getCurve(channel) { ... }
```

### Phase 3: Calibration File Support

#### Step 3.1 — `.ady` Import
Parse Denon MultEQ Editor JSON export. Normalize to internal channel format.

**Route:** `POST /api/a1evo/parse-ady` — accepts uploaded `.ady` file → returns normalized channel data

#### Step 3.2 — `.oca` Save/Load
A1 Evo's native calibration format (JSON with version envelope).

**Route:** `POST /api/a1evo/save-oca` — write JSON to CIFS at `/openclaw/media/calibrations/`
**Route:** `GET /api/a1evo/load-oca?name=<filename>` — read from CIFS

```javascript
// Save:
const ocaPath = path.join(CIFS_ROOT, 'openclaw/media/calibrations', filename + '.oca');
fs.writeFileSync(ocaPath, JSON.stringify(ocaData));

// Load:
const ocaPath = path.join(CIFS_ROOT, 'openclaw/media/calibrations', filename + '.oca');
return JSON.parse(fs.readFileSync(ocaPath, 'utf8'));
```

### Phase 4: Frontend — A1 Evo Tab in SPA

**File:** `/root/.openclaw/workspace/audyssey-rew-tuner/index.html` — add as second tab

#### Step 4.1 — Tab Navigation
Add tab bar to existing SPA header:
```html
<div class="tab-bar">
  <button class="tab active" data-tab="audyssey">Audyssey REW Tuner</button>
  <button class="tab" data-tab="a1evo">A1 Evo AcoustiX</button>
</div>
```

#### Step 4.2 — A1 Evo Tab HTML
Add the 3-column layout from `A1EvoAcoustiX_embedded.html` inside a `<div id="a1evo-panel" class="tab-panel">`.

**Three columns:**
1. **Target Response** — target curve select, chart, crossover frequency ranges (4 groups: fronts/center/surrounds/atmos), max EQ frequency limits
2. **Bass Management** — subwoofer controls, double bass, MIMO processing, sub EQ range, LPF for LFE, filter boost limits, THX mode
3. **Interactive** — volume levelling, manual alignment, custom filters, low volume compensation, tactile transducer

#### Step 4.3 — Chart.js Target Curve Display
From embedded HTML — use `curveChart` (Chart.js) to display selected target curve. Load curves via `GET /api/a1evo/target-curves`.

#### Step 4.4 — AVR Discovery UI
In A1 Evo tab — "Find AVR" button → `POST /api/a1evo/discover` → show discovered AVRs in dropdown → select and connect.

#### Step 4.5 — Settings Form → API Calls
On "START OPTIMIZATION" click — collect all form values → `POST /api/a1evo/rew-import-ir` → `POST /api/a1evo/rew-match-target` → get results → `POST /api/a1evo/transfer-filters`.

### Phase 5: Filter Transfer (Binary Protocol)

The SPEC.md describes a binary packet format for the full filter transfer (not just the ASCII MSSV/MSD/MST commands). This is used by `transfer_module.js` in the original binary.

For initial implementation, use the ASCII commands (MSSV/MSD/MST) which are simpler and may be sufficient. The binary protocol is Phase 5 (advanced).

**ASCII Command Approach (Phase 4 baseline):**
```
MSSVFL=63Hz,-3.5dB,Q=1.2
MSSVFL=100Hz,2.0dB,Q=2.0
...
```

**Binary Packet Approach (Phase 5):**
- `buildPacketConfig` → per-channel binary packets
- `hexWithChecksum` → AVR command packets
- Send multiple sample rates (48kHz, 96kHz, etc.)

---

## File Structure

```
/root/.openclaw/workspace/home-console/
  server.js                          # existing — mount a1-evo routes
  a1-evo-server.js                   # NEW — A1 Evo SSR module
  a1-evo-transfer.js                 # NEW — binary filter transfer (Phase 5)
/root/.openclaw/workspace/audyssey-rew-tuner/
  index.html                         # existing Audyssey page — add A1 Evo tab here
  a1-evo-tab.html                    # NEW — A1 Evo tab HTML/JS (injected into index.html)
  /target_curves/                    # existing — acoustix.txt and other curves
```

**A1 Evo tab is added to `index.html`** (not a separate file) — share SPA infrastructure.

---

## Testing Approach

### 1. Server Routes (Node.js)
```bash
# Test SSDP discovery (requires AVR on network)
curl -X POST http://localhost:18790/api/a1evo/discover

# Test AVR connection
curl -X POST http://localhost:18790/api/a1evo/connect \
  -H 'Content-Type: application/json' \
  -d '{"host":"192.168.1.XX"}'

# Test command sending
curl -X POST http://localhost:18790/api/a1evo/send-command \
  -H 'Content-Type: application/json' \
  -d '{"command":"MSSVFL=63Hz,-3.5dB,Q=1.2"}'
```

### 2. REW Integration
```bash
# Requires REW running with API enabled (port 4735)
# Test import IR
curl -X POST http://localhost:18790/api/a1evo/rew-import-ir \
  -H 'Content-Type: application/json' \
  -d '{"channel":"FL","irData":"<base64>","sampleRate":48000}'

# Test match target
curl -X POST http://localhost:18790/api/a1evo/rew-match-target \
  -H 'Content-Type: application/json' \
  -d '{"channel":"FL","targetCurveFile":"acoustix.txt"}'
```

### 3. File Operations
```bash
# Save calibration
curl -X POST http://localhost:18790/api/a1evo/save-oca \
  -H 'Content-Type: application/json' \
  -d @test-calibration.json

# Load calibration
curl http://localhost:18790/api/a1evo/load-oca?name=test-calibration

# Parse .ady file
curl -X POST http://localhost:18790/api/a1evo/parse-ady \
  -F 'file=@measurement.ady'
```

### 4. Frontend Testing
- Load Echo Console → switch to "A1 Evo AcoustiX" tab
- Click "Find AVR" → should show discovered receivers
- Select AVR and connect
- Select target curve → chart should render
- Adjust crossover/EQ settings
- Click "Start Optimization" → should trigger REW + transfer workflow

---

## Key Implementation Details

### Telnet Command Reference (ASCII mode)

**Channel names:** `FL`, `FR`, `C`, `SW`, `SL`, `SR`, `BL`, `BR`, `SBL`, `SBR`
**Height channels (when hasHeightSpeakers):** `FD`, `FS`, `TM`, `RL`, `RR`

**PEQ Filter:**
```
MSSVFL=63Hz,-3.5dB,Q=1.2
MSSV<ch>=<freq>Hz,<gain>dB,Q=<q>
```

**Speaker Distance (in mm):**
```
MSDFL3000   → FL at 3000mm
MSD<ch><distance_mm>
```

**Trim (in 0.1 dB units):**
```
MSTFL105    → FL trim +10.5 dB
MST<ch><trim_x10>
```

### SSDP Discovery Details

**Multicast address:** `239.255.255.250:1900`
**ST header:** `urn:schemas-denon-com:device:ACT-DenonDeviceService:1`
**Timeout:** 3 seconds (MX: 3)
**Parse:** Extract `LOCATION:` header → GET device XML → parse `modelName`, `modelDescription`

### REW API Endpoints (from SPEC.md)

| REW Endpoint | Purpose |
|---|---|
| `POST /eq/import-impulse` | Import IR as base64 float32 |
| `POST /eq/filter` | Configure filter tasks |
| `POST /eq/match-target` | Match target curve |
| `GET /measurements/curve` | Get resulting curve data |
| `GET /eq/house-curve` | House curve |
| `POST /eq/export-raw` | Export filter coefficients |

### State Management

Server-side state (in-memory, per-session):
```javascript
const sessions = new Map(); // session token → {
  // A1 Evo state:
  avr: { host, port, model, connected, socket },
  currentCalibration: { /* .oca data */ },
  targetCurve: 'acoustix.txt',
  settings: { /* form values from last optimization */ }
}
```

---

## Risks & Notes

1. **AVR must be on same network** — SSDP multicast won't work across VLANs/subnets
2. **REWARD not tested** — REW API at port 4735 must be verified working
3. **Binary transfer protocol** — Phase 5 for full feature parity; ASCII commands first
4. **Telnet negotiation** — AVR may send IAC (0xFF) during connection; handle it properly
5. **Multi-Sub support** — SW1/SW2 channels if multiple subwoofers
6. **Height speaker detection** — detect from AVR model via SSDP

---

## Future Enhancements (out of scope for initial build)

- Subwoofer level balancing UI (MSQ query commands)
- Full MIMO processing workflow
- THX allpass filter application
- Multi-sub phase alignment
- Bass shaker/tactile transducer support
- Calibration history/versioning