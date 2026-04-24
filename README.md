# Audyssey REW Tuner — A1 Evo AcoustiX Transfer Tools

Tools for reverse-engineering and transferring Audyssey calibrations to Denon/Marantz AVRs via the binary protocol. Supports full OCA calibrations and individual PEQ filters from REW.

## What's Working ✅

**Full OCA calibration transfer** (verified Apr 24, 2026):
```bash
python3 oca_transfer.py 192.168.50.2
```

**REW PEQ → AVR transfer** (verified Apr 24, 2026):
```bash
python3 rew_to_audyssey.py --test            # test with sample data
python3 rew_to_audyssey.py --auto            # from REW API
python3 rew_to_audyssey.py --file filters.json  # from JSON
python3 rew_to_audyssey.py --eqx demo.eqx     # from .eqx calibration file
```

**Export REW PEQ to .eqx:**
```bash
python3 rew_to_audyssey.py --auto --save-eqx calibration.eqx
```

## File Inventory

### Transfer Scripts
| File | Purpose |
|------|---------|
| `oca_transfer.py` | **Main transfer script** — sends full OCA calibration via binary protocol |
| `rew_to_audyssey.py` | **REW PEQ → AVR** — converts PEQ filters to biquad coefficients and transfers |
| `rew_to_audyssey.py --eqx` | **Future-ready** — loads/saves `.eqx` calibration files |

### Data Files
| File | Purpose |
|------|---------|
| `A1EvoAcoustiX_Apr24_1844_1777065760128..oca` | Latest OCA calibration (Apr24 18:44 run) |
| `acoustix_transfer_1777065760128..pcapng` | pcap of Apr24 transfer (verified correct SW trim) |
| `A1EvoAcoustiX_Apr24_1844_1777066154375..html` | OCA log HTML from Apr24 run |

### Documentation
| File | Purpose |
|------|---------|
| `SPEC.md` | Full protocol spec — binary format, command reference, confirmed encoding |
| `IMPLEMENTATION_PLAN.md` | Plan for Echo Console A1 Evo tab integration |
| `docs/` | Additional notes and research |

## Transfer Protocol — Confirmed Details

### Port 1256 — Binary TCP
| Message | Purpose |
|---------|---------|
| `GET_AVRINF` | Query AVR capabilities |
| `SET_SETDAT` | Set distances, trims, crossovers |
| `SET_COEFDT` | Set filter coefficients (126 × LE float32 per message) |

**Key finding (April 24, 2026):**
- Coefficient offset: TCP payload **offset 22** (not 24)
- Coefficient encoding: **little-endian** IEEE 754 float32 (not big-endian)
- Meta field: always `02 00 01 00` for coefficient messages

### Port 23 — Telnet (ASCII)
| Command | Purpose |
|---------|---------|
| `MSSV<ch>=<freq>Hz,<gain>dB,Q=<q>` | Set PEQ filter |
| `MSD<ch><distance_mm>` | Set distance |
| `MST<ch><trim_x10>` | Set trim |
| `ZM?AUDYON` | Apply calibration |

## Verified Results (Apr 24, 2026)

After running `oca_transfer.py` and power cycling the X3800H:
- FL: -0.5dB, 2.75m ✓
- SW1: -0.5dB, 2.81m ✓
- SW2: -2.5dB, 2.82m ✓

## Future: .eqx Calibration Format

**.eqx** is the planned open calibration format for this project — designed for extensibility, future room measurement sources, and full interoperability with REW and other measurement tools.

### Design Goals
- Support room measurements from any source (REW, ARTA, REW beta, etc.)
- Store full EQ data independent of any AVR-specific binary format
- Easy to generate from room measurement files (REW txt, CSV, etc.)
- Convertible to OCA for Denon/Marantz transfer, or direct binary for other AVRs

### .eqx Format (v1.0 draft)
```json
{
  "version": "1.0",
  "appVersion": "3.0",
  "createdAt": "2026-04-24T18:44:00.000Z",
  "model": "AVR-X3800H",
  "eqType": 2,
  "channels": [{
    "channel": 0,
    "channelName": "FL",
    "distanceInMeters": 2.75,
    "trimAdjustmentInDbs": -0.5,
    "peq": [
      { "freq": 63, "gain": -2.5, "Q": 1.2, "type": "PEQ" },
      { "freq": 125, "gain": 1.5, "Q": 1.4, "type": "PEQ" }
    ],
    "filter": [ /* raw IIR coefficients */ ],
    "sr": 48000
  }],
  "subwoofer": {
    "distanceInMeters": 2.81,
    "trimAdjustmentInDbs": -5.0
  }
}
```

### Planned .eqx Features
- [ ] Parse REW measurement exports (txt, csv)
- [ ] Generate .eqx from room measurement data
- [ ] Convert .eqx → OCA (Denon/Marantz)
- [ ] Convert .eqx → direct binary (other AVR brands)
- [ ] Target curve integration
- [ ] Multi-sub optimization support

## Next Steps
- [ ] Add SR codes beyond 0/52/57 (96kHz = 184)
- [ ] Implement binary SET_SETDAT builder (currently using pcap bytes)
- [ ] Echo Console tab for one-click transfer
- [ ] .eqx generation from REW measurement files
- [ ] Support for other AVR models (currently tested on X3800H)
