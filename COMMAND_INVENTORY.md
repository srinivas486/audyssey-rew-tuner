# Command Inventory — transfer.js vs oca_transfer.py

**Reference:** transfer.js (3,674 lines)  
**Compared against:** oca_transfer.py (1,381 lines)  
**Date:** 2026-04-28

---

## Command Category 1: Binary TCP Protocol (Port 1256)

transfer.js and oca_transfer.py both use port 1256 for binary packet commands. Both implement the same core transfer commands.

### ✅ Already in oca_transfer.py

| Command | Purpose | Hex |
|---------|---------|-----|
| `GET_AVRINF` | Get AVR info (EQType, CoefWaitTime, etc.) | `54001300004745545f415652494e460000006c` |
| `GET_AVRSTS` | Get AVR status | `54001300004745545f41565253545300000089` |
| `ENTER_AUDY` | Enter calibration mode | `5400130000454e5445525f4155445900000077` |
| `INIT_COEFS` | Initialize coefficients | `5400130000494e49545f434f4546530000006a` |
| `FINZ_COEFS` | Finalize coefficients | `540013000046494e5a5f434f4546530000006d` |
| `SET_AUDYFINFLG` | Set calibration finalize flag | Direct binary format |
| `EXIT_AUDMD` | Exit calibration mode | `5400130000455849545f4155444d440000006b` |
| `SET_SETDAT` | Configuration (distances, trims, crossovers) | Binary JSON wrapper |
| `SET_COEFDT` | Filter coefficients (126 float32 per packet) | Direct binary format (531 bytes) |

### ❌ NOT in oca_transfer.py

| Command | Purpose | transfer.js implementation |
|---------|---------|---------------------------|
| `SET_POSNUM` | Set measurement position number for AVR-guided measurement | `buildAvrPacket('SET_POSNUM', jsonString)` then `sendFunction(packet.toString('hex'), ...)` |
| `START_CHNL` | Start measurement sweep for a specific channel | `buildAvrPacket('START_CHNL', jsonString)` → returns `{Distance, Level, ...}` |
| `GET_RESPON` | Fetch impulse response data after measurement | `buildAvrPacket('GET_RESPON', jsonString)` → returns multi-packet binary float32 data |

---

## Command Category 2: Telnet ASCII Protocol (Port 23)

transfer.js implements a full telnet command suite on port 23.

### ✅ Already in oca_transfer.py (partial)

| Command | Purpose | Implementation |
|---------|---------|----------------|
| `SPPR ?` | Query current preset | `switch_preset()` — connects, queries, switches, closes |
| `SPPR <N>` | Set preset to N | `switch_preset()` — same function |

### ❌ Missing from oca_transfer.py

| Command | Purpose | How transfer.js uses it |
|---------|---------|------------------------|
| `ZM?` | Query power status | `executeCommand('ZM?', /ZM(ON\|OFF)/i, ...)` |
| `ZMON` | Power ON | `executeCommand('ZMON', /ZMON/i, ...)` + 5s delay + verify |
| `ZMOFF` | Power OFF | Not explicitly called in transfer.js (just queries) |
| `SSLFL <val>` | Set LPF for LFE (3-digit Hz) | Query + SET pattern: `SSLFL xxx` with verification |
| `SSSWM <val>` | Set bass mode (older models) | Query + SET pattern: `SSSWM LFE/LFE+M/L+M` |
| `SSSWO <val>` | Set subwoofer mode (newer models) | Query + SET pattern: `SSSWO LFE/LFE+M/L+M` |
| `PSSWL OFF` | Disable subwoofer level control (older) | Direct echo confirmation pattern |
| `SSCFRFRO FUL` | Set front speakers to full range | Direct echo (no query) |
| `SSBELFRO <val>` | Set front bass extraction frequency | Direct echo (no query) |

**Note on bass mode commands:**
- `SSSWM` is for older AVR models (flag: `isNewModel = false`)
- `SSSWO` is for newer AVR models (flag: `isNewModel = true`)
- The model detection from `GET_AVRINF` / AVR status determines which to use

---

## Command Category 3: Measurement Workflow (AVR-Guided)

transfer.js has a complete measurement workflow (Option 2 in the menu) that oca_transfer.py does NOT implement at all. This is a major feature gap.

### Measurement Flow (transfer.js)

```
1. Connect to port 1256
2. GET_AVRINF → detect channels, subwoofer count
3. UPnP/SSDP discovery (for initial config only)
4. User selects number of mic positions
5. ENTER_AUDY → enter calibration mode
6. For each position:
   a. SET_POSNUM(position) → tell AVR which position
   b. For each detected channel:
      - START_CHNL(channelId) → trigger AVR sweep
      - Wait for response {Distance, Level, Freq, ...}
   c. For FL and FR channels (position 1):
      - GET_RESPON(channelId) → fetch full impulse response
   d. For subwoofer:
      - Re-cable SW1 to SW1 pre-out
      - GET_RESPON('SW1') → fetch sub impulse response
7. EXIT_AUDMD → exit calibration mode
8. Save .ady file (Denon MultEQ Editor export format)
```

**Key commands for measurement:**
- `SET_POSNUM` — `{"Position": N, "ChSetup": [...]}`
- `START_CHNL` — `{"Channel": "FL"}` → returns `{"Distance": 3000, "Level": -0.5, "Freq": 7, "PG": 85}`
- `GET_RESPON` — `{"ChData": "FL"}` → returns multi-packet binary float32 impulse data

---

## Command Category 4: UPnP/SSDP Discovery

transfer.js implements AVR auto-discovery via SSDP multicast on port 1900.

### ❌ NOT in oca_transfer.py

| Feature | transfer.js implementation |
|---------|---------------------------|
| SSDP discovery | `UPNPDiscovery` class, sends `M-SEARCH` to `239.255.255.250:1900` |
| Interactive device selection | inquirer prompt if multiple devices found |
| Model detection from UPnP XML | Parses `/goform/` XML for model name |
| /goform/ XML fallback | Fetches `http://<ip>/goform/` for model confirmation |

---

## Command Category 5: Audio EQ Commands (Port 23)

From SPEC.md, these Telnet commands are for setting speaker EQ:

| Command | Purpose | Example |
|---------|---------|---------|
| `MSSV<ch>=<freq>Hz,<gain>dB,Q=<q>` | Set PEQ filter | `MSSVFL=63Hz,-3.5dB,Q=1.2` |
| `MSD<ch><distance_mm>` | Set distance (mm) | `MSDFL3000` |
| `MST<ch><trim_x10>` | Set trim (0.1 dB) | `MSTFL105` = +10.5 dB |
| `MSSV?<ch>` | Query filter | `MSSV?FL` |

**Status in oca_transfer.py:** NOT implemented. These are mentioned in SPEC.md but not in transfer.js main menu (transfer.js uses binary SET_SETDAT instead for distances/trims).

---

## Summary: What's Missing from oca_transfer.py

### High Priority (useful standalone commands)

1. **`power_on(ip)`** — Connect to telnet, check `ZM?`, send `ZMON` if off, wait 5s, verify
2. **`power_off(ip)`** — Connect to telnet, send `ZMOFF`
3. **`get_power_status(ip)`** — Connect to telnet, send `ZM?`, parse `ZMON`/`ZMOFF`
4. **`set_audio_settings(ip, lpf_lfe, bass_mode, is_new_model, xover)`** — Combined function for `SSLFL`, `SSSWM`/`SSSWO`, `SSCFRFRO`, `SSBELFRO`
5. **`query_audio_settings(ip)`** — Query current `SSLFL`, `SSSWM`/`SSSWO` values

### Medium Priority (measurement workflow — large feature)

6. **`run_measurement(ip, positions)`** — Full AVR-guided measurement: `ENTER_AUDY` → `SET_POSNUM` → `START_CHNL` → `GET_RESPON` → `EXIT_AUDMD`
7. **UPnP discovery** — AVR auto-discovery via SSDP

### Lower Priority (nice to have)

8. **Audio EQ commands** (`MSSV`, `MSD`, `MST`) — Direct speaker control via telnet (these go through SET_SETDAT in transfer.js but could be useful as standalone telnet commands)

---

## Implementation Plan

### Phase 1: Power + Audio Settings (standalone utilities)

**Files:** `oca_transfer.py` additions

```python
# === New constants (add near ENTER_AUDY_HEX) ===
ZMON_HEX = 'ZMON\r'
ZMOFF_HEX = 'ZMOFF\r'
ZM_QUERY_HEX = 'ZM?\r'

# === New functions ===
def get_power_status(ip: str) -> str:
    """Query AVR power status via Telnet. Returns 'ON', 'OFF', or 'UNKNOWN'."""
    # Connect to port 23, send 'ZM?\r', read response, parse ZMON/ZMOFF

def power_on(ip: str, timeout: float = 15.0) -> bool:
    """Turn AVR on. Returns True if successful."""
    # Check power status first, send ZMON if off, wait 5s, verify with ZM?

def power_off(ip: str) -> bool:
    """Turn AVR off via ZMOFF."""
    # Connect, send ZMOFF, close

def set_audio_settings(ip: str, lpf_lfe: int = 120, bass_mode: str = 'LFE',
                       is_new_model: bool = False, xover: int = None) -> dict:
    """Set SSLFL, SSSWM/SSSWO, SSCFRFRO, SSBELFRO via Telnet.
    Returns dict of {setting: value} for what was set.
    """
    # Use detect_model(ip) to determine is_new_model if not provided
    # Send commands with query-verification pattern from transfer.js

def query_audio_settings(ip: str) -> dict:
    """Query current SSLFL, SSSWM/SSSWO settings."""
    # Send SSLFL ?, SSSWM ? / SSSWO ?, parse responses
```

### Phase 2: Measurement Workflow

**Files:** `oca_transfer.py` additions (or new `oca_measure.py`)

```python
# === New constants ===
START_CHNL_HEX = ...  # built with buildAvrPacket
GET_RESPON_HEX = ...  # built with buildAvrPacket
SET_POSNUM_HEX = ... # built with buildAvrPacket

# === New functions ===
def set_measurement_position(sock, position: int, channel_setup: List[str]) -> bool:
    """SET_POSNUM command via port 1256."""
    # Build JSON: {"Position": N, "ChSetup": [...]}
    # Send via send_and_wait_ack

def start_channel_measurement(sock, channel_id: str, timeout: float = 12.0) -> dict:
    """START_CHNL command. Returns {Distance, Level, Freq, PG}."""
    # Build packet, send, parse JSON response

def get_channel_impulse_response(sock, channel_id: str, timeout: float = 20.0) -> List[float]:
    """GET_RESPON command. Returns list of float32 impulse data."""
    # Multi-packet receive with sequence number tracking
    # Use parseIncomingPacket logic from transfer.js

def run_measurement(ip: str, positions: int = 1) -> dict:
    """Full AVR-guided measurement. Returns allPositionsData dict."""
    # Connect to port 1256
    # GET_AVRINF → detect channels
    # ENTER_AUDY
    # For each position 1..N:
    #   SET_POSNUM
    #   For each channel: START_CHNL → GET_RESPON
    # EXIT_AUDMD
    # Return structured data
```

### Phase 3: UPnP Discovery

**Files:** `oca_discovery.py` (new file)

```python
# === New functions ===
def discover_avr(timeout: float = 5.0) -> List[dict]:
    """SSDP/UPnP discovery. Returns list of {ip, model, name}."""
    # Send M-SEARCH to 239.255.255.250:1900
    # Collect responses, resolve HTTP (or use async approach)

def interactive_discovery() -> dict:
    """Interactive AVR selection if multiple found."""
    # discover_avr() → if len > 1: inquirer prompt → return selected
```

---

## Transfer.js Command Quick Reference

### Binary Commands (Port 1256)

| Command | Payload | Response |
|---------|---------|----------|
| `GET_AVRINF` | none (raw hex) | JSON: `{EQType, CVVer, CoefWaitTime, ...}` |
| `GET_AVRSTS` | none (raw hex) | JSON: `{Power, ActiveChannels, ChSetup, ...}` |
| `ENTER_AUDY` | none (raw hex) | ACK byte `0x00` |
| `INIT_COEFS` | none (raw hex) | ACK byte `0x00` |
| `FINZ_COEFS` | none (raw hex) | ACK byte `0x00` |
| `SET_AUDYFINFLG` | JSON: `{"AudyFinFlg": "Fin"}` | ACK byte `0x00` |
| `EXIT_AUDMD` | none (raw hex) | ACK byte `0x00` |
| `SET_SETDAT` | JSON config | ACK byte `0x00` |
| `SET_COEFDT` | 531 bytes binary | ACK byte `0x00` |
| `SET_POSNUM` | JSON: `{"Position": N, "ChSetup": [...]}` | ACK byte `0x00` |
| `START_CHNL` | JSON: `{"Channel": "FL"}` | JSON: `{"Distance": N, "Level": dB, ...}` |
| `GET_RESPON` | JSON: `{"ChData": "FL"}` | Multi-packet binary float32 |

### Telnet Commands (Port 23)

| Command | Purpose | Response |
|---------|---------|----------|
| `ZM?` | Query power | `ZMON\r` or `ZMOFF\r` |
| `ZMON` | Power on | Echoes `ZMON\r` |
| `ZMOFF` | Power off | Echoes `ZMOFF\r` |
| `SPPR ?` | Query preset | `SPPR 1\r` or `SPPR 2\r` |
| `SPPR <N>` | Set preset | Echoes `SPPR N\r` |
| `SSLFL ?` | Query LPF for LFE | `SSLFL 120\r` |
| `SSLFL <val>` | Set LPF for LFE | Echoes `SSLFL xxx\r` |
| `SSSWM ?` | Query bass mode | `SSSWM LFE\r` |
| `SSSWM <val>` | Set bass mode | Echoes `SSSWM LFE\r` |
| `SSSWO ?` | Query subwoofer mode | `SSSWO LFE\r` |
| `SSSWO <val>` | Set subwoofer mode | Echoes `SSSWO LFE\r` |
| `PSSWL OFF` | Subwoofer level off | Direct echo only |
| `SSCFRFRO FUL` | Front speakers full range | Direct echo only |
| `SSBELFRO <val>` | Front bass extraction freq | Direct echo only |

### Packet Format: buildAvrPacket (for JSON commands)

```javascript
// Used for: SET_SETDAT, SET_POSNUM, START_CHNL, GET_RESPON, SET_AUDYFINFLG
function buildAvrPacket(commandName, jsonPayloadString, seqNum = 0, lastSeqNum = 0) {
    // Header: marker(1) + length(2) + seq(1) + lastSeq(1) = 5 bytes
    // Footer: checksum(1) byte
    // Total = 5 + cmdLen + paramLen + 1
}
```

### Packet Format: SET_COEFDT (direct binary, NO buildAvrPacket)

```javascript
// 531 bytes total, NO checksum
// marker(1) + counter(3) + flag(1) + cmd(10) + null(1) + paramLen(2) + meta(4) + channel(1) + sr(1) + coefs(504)
```
