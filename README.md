# Audyssey REW Tuner — A1 Evo AcoustiX Transfer Tools

Tools for reverse-engineering and transferring Audyssey calibrations to Denon/Marantz AVRs via the binary protocol.

## Quick Start

```bash
# Transfer OCA to preset A (default)
python3 oca_transfer.py calibration.oca

# Transfer OCA to preset B
python3 oca_transfer.py calibration.oca --preset B

# With specific AVR IP
python3 oca_transfer.py calibration.oca 192.168.50.2 --preset A

# REW PEQ → AVR
python3 rew_to_audyssey.py --test            # test with sample data
python3 rew_to_audyssey.py --auto            # from REW API
python3 rew_to_audyssey.py --eqx demo.eqx    # from .eqx file
```

## File Inventory

### Transfer Scripts
| File | Purpose |
|------|---------|
| `oca_transfer.py` | Transfer .oca calibration files to AVR (preset A or B) |
| `rew_to_audyssey.py` | Convert PEQ filters from REW and transfer to AVR |

### Data Files
| File | Purpose |
|------|---------|
| `A1EvoAcoustiX_Apr24_1844_1777065760128..oca` | Latest OCA calibration (Apr24 18:44 run) |
| `acoustix_transfer_1777065760128..pcapng` | pcap of Apr24 transfer (verified correct SW trim) |

### Documentation
| File | Purpose |
|------|---------|
| `SPEC.md` | Full protocol spec — binary format, command reference, confirmed encoding |
| `IMPLEMENTATION_PLAN.md` | Plan for Echo Console A1 Evo tab integration |

## Key Features

### OCA Transfer
- Any `.oca` file as input — no hardcoded paths
- Auto-detects matching `.pcapng` next to OCA for config bytes
- Falls back to building config from OCA channel data
- **Preset A/B support** for X3800H dual Audyssey slots
- Config messages extracted from pcap (distances, trims, crossovers)
- All coefficients sent as LE float32 at TCP offset 22

### X3800H Dual Presets
The X3800H stores two full Audyssey calibrations (A and B). Transfer to the slot you want:
- `python3 oca_transfer.py file.oca --preset A` → Audyssey Preset A
- `python3 oca_transfer.py file.oca --preset B` → Audyssey Preset B
- Switch between presets via AVR UI or `ZM?` via Telnet port 23

## Transfer Protocol — Confirmed Details

### Port 1256 — Binary TCP
| Message | Purpose |
|---------|---------|
| `GET_AVRINF` | Query AVR capabilities |
| `SET_SETDAT` | Set distances, trims, crossovers |
| `SET_COEFDT` | Set filter coefficients (126 × LE float32 per message) |

**Key finding (April 24, 2026):**
- Coefficient offset: TCP payload **offset 22**
- Coefficient encoding: **little-endian** IEEE 754 float32
- Meta field: `02 00 01 00` for coefficient messages
- Counter base: `0x1300`, increment: `(msg_idx << 8) + channel_idx`

### Port 23 — Telnet (ASCII)
| Command | Purpose |
|---------|---------|
| `ZM?AUDYON` | Apply calibration (after transfer) |
| `ZM?` | Cycle through Audyssey presets |

## Verified Results (Apr 24, 2026)

After running `oca_transfer.py` and power cycling the X3800H:
- FL: -0.5dB, 2.75m ✓
- SW1: -0.5dB, 2.81m ✓
- SW2: -2.5dB, 2.82m ✓

## Next Steps
- [ ] Verify preset B transfer works (need to test with second OCA file)
- [ ] Build config from OCA when no pcap available (fallback mode)
- [ ] Echo Console tab for one-click transfer
- [ ] .eqx generation from REW measurements
## Usage Examples

```bash
# Transfer to preset 1 (default)
python3 oca_transfer.py calibration.oca

# Transfer to preset 2
python3 oca_transfer.py calibration.oca --preset 2

# With specific IP
python3 oca_transfer.py my_oca.oca 192.168.50.2 --preset 1
```
