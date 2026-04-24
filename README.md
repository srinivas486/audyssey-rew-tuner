# Audyssey REW Tuner — A1 Evo AcoustiX Transfer Tools

Tools for reverse-engineering and transferring Audyssey calibrations to Denon/Marantz AVRs via the binary protocol.

## What's Working ✅

**Full OCA calibration transfer to AVR (verified April 24, 2026):**
```bash
python3 oca_transfer.py 192.168.50.2
```
This transfers all 11 channels, 16321 filter coefficients per channel, using the confirmed binary protocol on port 1256.

## File Inventory

### Transfer Scripts
| File | Purpose |
|------|---------|
| `oca_transfer.py` | **Main transfer script** — sends full OCA calibration via binary protocol |
| `rew_to_audyssey.py` | REW PEQ → AVR transfer via ASCII Telnet commands |
| `avr_proto_*.py` | Development history — protocol experiments |

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

## Usage

### Full OCA Transfer
```bash
# Connect AVR (port 1256) and transfer full calibration
python3 oca_transfer.py [AVR_IP]

# Defaults to 192.168.50.2 if no IP given
python3 oca_transfer.py
```

### REW Integration
```bash
# Test with REW API
python3 rew_to_audyssey.py --auto
```

## Next Steps
- [ ] Add SR codes beyond 0/52/57 (96kHz = 184)
- [ ] Implement binary SET_SETDAT builder (currently using pcap bytes)
- [ ] Echo Console tab for one-click transfer
- [ ] Support for other AVR models (currently tested on X3800H)
