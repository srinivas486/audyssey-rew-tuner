# Audyssey REW Tuner

A single-page HTML tool for tuning Denon Audyssey `.ady` files using Room EQ Wizard (REW).

## What It Does

1. **Parses** your Denon MultEQ Editor `.ady` file — extracts channel measurements, distances, trims, delays, and polarity
2. **Imports** impulse responses into REW via its REST API
3. **Generates** corrective PEQ filters matched to a target curve of your choice
4. **Exports** a tuned `.ady` file ready to load back into the Denon MultEQ Editor app and send to your AVR

## Target Hardware

- **AVR:** Denon X3800H (MultEQ-X, up to 20 PEQ bands per channel)
- **Software:** REW (Room EQ Wizard) v5.30+ with API mode enabled

## Requirements

- REW running on the same machine with API server enabled
  - REW → Preferences → API → Enable API Server (default port: 4735)
- A modern browser (Chrome, Firefox, Edge) — open `index.html` directly from disk (`file://`)
- A `.ady` file exported from the Denon MultEQ Editor app

## Usage

1. Open `index.html` in your browser
2. Start REW and enable the API server
3. Click **Test Connection** — confirm green status
4. Drag-and-drop your `.ady` file (or use Browse)
5. Select your target curve preset and adjust shelf controls
6. Click **Import to REW**
7. Click **Run EQ Matching**
8. Click **Export Tuned ADY** — download your tuned file
9. Open the tuned `.ady` in Denon MultEQ Editor and send to the X3800H

## Target Curve Presets

| Preset | Description |
|---|---|
| Flat | Pure reference — 0 dB everywhere |
| Harman Home | +6 dB shelf below 100 Hz, gentle roll-off above 2 kHz |
| House Curve −0.5/oct | Subtle warmth — −0.5 dB/octave from 1 kHz |
| House Curve −1.0/oct | Warmer/darker — −1.0 dB/octave from 1 kHz |
| X-Curve | Cinema standard — −3 dB/octave above 2 kHz |
| Custom CSV | Upload your own `frequency,dB` CSV |

## No Build Step

This tool is a single `index.html` — no npm, no bundler, no server. Open it directly in a browser.

## License

MIT

## Credits

Inspired by [A1Evo MJ Custom](https://github.com/navid0308/A1Evo_MJ_Custom) by navid0308.
