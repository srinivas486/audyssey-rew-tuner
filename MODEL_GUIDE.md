# MODEL_GUIDE.md — Audyssey Model-Specific Handling Reference

_This document describes how `transfer.js` handles different Audyssey AVR models.
_Python implementation (`oca_transfer.py`) should match this behavior exactly._

---

## 1. EQType Detection (XT32 vs XT vs MultEQ)

EQType is returned by `GET_AVRINF` as part of the JSON response.

### Detection Logic

```javascript
if (eqTypeString.includes('XT32')) enMultEQType = 2;   // MultEQ XT32
else if (eqTypeString.includes('XT')) enMultEQType = 1; // MultEQ XT
else if (eqTypeString.includes('MultEQ')) enMultEQType = 0; // MultEQ
```

### In transfer.js

```javascript
function formatDataForFrontend(details) {
    const eqTypeString = details.eqTypeString || "";
    if (typeof eqTypeString === 'string' && eqTypeString) {
        if (eqTypeString.includes('XT32')) enMultEQType = 2;
        else if (eqTypeString.includes('XT')) enMultEQType = 1;
        else if (eqTypeString.includes('MultEQ')) enMultEQType = 0;
    }
    // ...
    return { enMultEQType, subwooferNum, ampAssign, ampAssignInfo, detectedChannels };
}
```

### Python Equivalent

```python
def detect_mult_eq_type(eq_type_str: str) -> str:
    """Detect MultEQ type from EQType string."""
    if 'XT32' in eq_type_str:
        return 'XT32'
    elif 'XT' in eq_type_str:
        return 'XT'
    else:
        return 'MultEQ'
```

---

## 2. Coefficient Type Handling (float vs fixed32)

AVR reports its coefficient data type via `DType` field in `GET_AVRINF` response.

### Data Type Values

- `'float'` → AVR accepts IEEE 754 little-endian float32
- `'fixedA'` or any string starting with `'fixed'` → AVR uses fixed-point 32-bit integers

### JavaScript: javaFloatToFixed32bits()

Converts a JavaScript float to the AVR's internal fixed-point representation:

```javascript
function javaFloatToFixed32bits(f) {
    const isNegative = f < 0.0;
    const absF = Math.abs(f);
    let resultInt = 0;

    if (absF >= 1.0) {
        resultInt = 0x7FFFFFFF;  // Clamp to max positive
    } else {
        let f2 = absF;
        resultInt = 0;
        for (let i2 = 0; i2 < 31; i2++) {
            resultInt <<= 1;
            f2 = (f2 - Math.trunc(f2)) * 2.0;
            if (f2 >= 1.0) {
                resultInt |= 1;
            }
        }
    }

    if (isNegative) {
        resultInt = (~resultInt) | 0x80000000;  // Two's complement for negative
    }
    return resultInt;
}
```

### Python Equivalent

```python
def java_float_to_fixed32bits(f: float) -> int:
    """Convert float to AVR fixed-point 32-bit representation."""
    is_negative = f < 0.0
    abs_f = abs(f)

    if abs_f >= 1.0:
        result_int = 0x7FFFFFFF  # Clamp to max positive
    else:
        f2 = abs_f
        result_int = 0
        for _ in range(31):
            result_int <<= 1
            f2 = (f2 - int(f2)) * 2.0
            if f2 >= 1.0:
                result_int |= 1

    if is_negative:
        result_int = (~result_int) & 0xFFFFFFFF | 0x80000000

    return result_int
```

### Buffer Conversion Functions

```javascript
// Float → little-endian float32 buffer
const floatToBufferLE = float => {
    const buf = Buffer.alloc(BYTES_PER_FLOAT);  // 4
    buf.writeFloatLE(float, 0);
    return buf;
};

// Fixed32 int → little-endian int32 buffer
const fixed32IntToBufferLE = fixedInt => {
    fixedInt = Math.max(-2147483648, Math.min(2147483647, fixedInt));
    const buf = Buffer.alloc(BYTES_PER_FLOAT);
    buf.writeInt32LE(fixedInt, 0);
    return buf;
};
```

---

## 3. Channel Byte Mapping Per Model

The `channelByteTable` maps channel IDs to their byte values for different AVR types.

### Channel Byte Table

```javascript
const channelByteTable = {
    FL:  { eq2: 0x00, neq2: 0x00, griffin: 0x00 },
    C:   { eq2: 0x01, neq2: 0x01, griffin: 0x01 },
    FR:  { eq2: 0x02, neq2: 0x02, griffin: 0x02 },
    FWR: { eq2: 0x15, neq2: 0x15, griffin: 0x15 },
    SRA: { eq2: 0x03, neq2: 0x03, griffin: 0x03 },
    SRB: { eq2: null, neq2: 0x07, griffin: null },
    SBR: { eq2: 0x07, neq2: 0x07, griffin: 0x07 },
    SBL: { eq2: 0x08, neq2: 0x08, griffin: 0x08 },
    SLB: { eq2: null, neq2: 0x0d, griffin: null },
    SLA: { eq2: 0x0c, neq2: 0x0c, griffin: 0x0c },
    FWL: { eq2: 0x1c, neq2: 0x1c, griffin: 0x1c },
    FHL: { eq2: 0x10, neq2: 0x10, griffin: 0x10 },
    CH:  { eq2: 0x12, neq2: 0x12, griffin: 0x12 },
    FHR: { eq2: 0x14, neq2: 0x14, griffin: 0x14 },
    TFR: { eq2: 0x04, neq2: 0x04, griffin: 0x04 },
    TMR: { eq2: 0x05, neq2: 0x05, griffin: 0x05 },
    TRR: { eq2: 0x06, neq2: 0x06, griffin: 0x06 },
    SHR: { eq2: 0x16, neq2: 0x16, griffin: 0x16 },
    RHR: { eq2: 0x13, neq2: 0x17, griffin: 0x13 },
    TS:  { eq2: 0x1d, neq2: 0x1d, griffin: 0x1d },
    RHL: { eq2: 0x11, neq2: 0x1a, griffin: 0x11 },
    SHL: { eq2: 0x1b, neq2: 0x1b, griffin: 0x1b },
    TRL: { eq2: 0x09, neq2: 0x09, griffin: 0x09 },
    TML: { eq2: 0x0a, neq2: 0x0a, griffin: 0x0a },
    TFL: { eq2: 0x0b, neq2: 0x0b, griffin: 0x0b },
    FDL: { eq2: 0x1a, neq2: 0x1a, griffin: 0x1a },
    FDR: { eq2: 0x17, neq2: 0x17, griffin: 0x17 },
    SDR: { eq2: 0x18, neq2: 0x18, griffin: 0x18 },
    BDR: { eq2: 0x18, neq2: 0x00, griffin: 0x1f },
    SDL: { eq2: 0x19, neq2: 0x19, griffin: 0x19 },
    BDL: { eq2: 0x19, neq2: 0x00, griffin: 0x20 },
    SW1: { eq2: 0x0d, neq2: 0x0d, griffin: 0x0d },
    SW2: { eq2: 0x0e, neq2: 0x0e, griffin: 0x0e },
    SW3: { eq2: 0x21, neq2: 0x21, griffin: 0x21 },
    SW4: { eq2: 0x22, neq2: 0x22, griffin: 0x22 }
};
```

### getChannelTypeByte() Logic

```javascript
function getChannelTypeByte(commandId, multEqType, isGriffin = false) {
    const entry = channelByteTable[commandId];
    if (!entry) {
        throw new Error(`Unknown channel commandId: ${commandId}`);
    }

    // Griffin takes precedence if available
    if (isGriffin && entry.griffin !== null) {
        return entry.griffin;
    }

    // XT32 uses eq2 mapping
    if (multEqType === 'XT32') {
        if (entry.eq2 !== null) return entry.eq2;
        // Fallback to neq2 if eq2 is null
        if (entry.neq2 !== null) return entry.neq2;
    }

    // XT and MultEQ use neq2 mapping
    if (multEqType === 'XT' || multEqType === 'MultEQ') {
        if (entry.neq2 !== null) return entry.neq2;
        // Fallback to eq2 if neq2 is null
        if (entry.eq2 !== null) return entry.eq2;
    }

    // Final fallback to griffin if available
    if (isGriffin && entry.griffin !== null) return entry.griffin;

    throw new Error(`No suitable channel byte mapping found for ${commandId}`);
}
```

### Python Equivalent

```python
CHANNEL_BYTE_TABLE = {
    'FL':  {'eq2': 0x00, 'neq2': 0x00, 'griffin': 0x00},
    'C':   {'eq2': 0x01, 'neq2': 0x01, 'griffin': 0x01},
    'FR':  {'eq2': 0x02, 'neq2': 0x02, 'griffin': 0x02},
    'FWR': {'eq2': 0x15, 'neq2': 0x15, 'griffin': 0x15},
    'SRA': {'eq2': 0x03, 'neq2': 0x03, 'griffin': 0x03},
    'SRB': {'eq2': None, 'neq2': 0x07, 'griffin': None},
    'SBR': {'eq2': 0x07, 'neq2': 0x07, 'griffin': 0x07},
    'SBL': {'eq2': 0x08, 'neq2': 0x08, 'griffin': 0x08},
    'SLB': {'eq2': None, 'neq2': 0x0d, 'griffin': None},
    'SLA': {'eq2': 0x0c, 'neq2': 0x0c, 'griffin': 0x0c},
    'FWL': {'eq2': 0x1c, 'neq2': 0x1c, 'griffin': 0x1c},
    'FHL': {'eq2': 0x10, 'neq2': 0x10, 'griffin': 0x10},
    'CH':  {'eq2': 0x12, 'neq2': 0x12, 'griffin': 0x12},
    'FHR': {'eq2': 0x14, 'neq2': 0x14, 'griffin': 0x14},
    'TFR': {'eq2': 0x04, 'neq2': 0x04, 'griffin': 0x04},
    'TMR': {'eq2': 0x05, 'neq2': 0x05, 'griffin': 0x05},
    'TRR': {'eq2': 0x06, 'neq2': 0x06, 'griffin': 0x06},
    'SHR': {'eq2': 0x16, 'neq2': 0x16, 'griffin': 0x16},
    'RHR': {'eq2': 0x13, 'neq2': 0x17, 'griffin': 0x13},
    'TS':  {'eq2': 0x1d, 'neq2': 0x1d, 'griffin': 0x1d},
    'RHL': {'eq2': 0x11, 'neq2': 0x1a, 'griffin': 0x11},
    'SHL': {'eq2': 0x1b, 'neq2': 0x1b, 'griffin': 0x1b},
    'TRL': {'eq2': 0x09, 'neq2': 0x09, 'griffin': 0x09},
    'TML': {'eq2': 0x0a, 'neq2': 0x0a, 'griffin': 0x0a},
    'TFL': {'eq2': 0x0b, 'neq2': 0x0b, 'griffin': 0x0b},
    'FDL': {'eq2': 0x1a, 'neq2': 0x1a, 'griffin': 0x1a},
    'FDR': {'eq2': 0x17, 'neq2': 0x17, 'griffin': 0x17},
    'SDR': {'eq2': 0x18, 'neq2': 0x18, 'griffin': 0x18},
    'BDR': {'eq2': 0x18, 'neq2': 0x00, 'griffin': 0x1f},
    'SDL': {'eq2': 0x19, 'neq2': 0x19, 'griffin': 0x19},
    'BDL': {'eq2': 0x19, 'neq2': 0x00, 'griffin': 0x20},
    'SW1': {'eq2': 0x0d, 'neq2': 0x0d, 'griffin': 0x0d},
    'SW2': {'eq2': 0x0e, 'neq2': 0x0e, 'griffin': 0x0e},
    'SW3': {'eq2': 0x21, 'neq2': 0x21, 'griffin': 0x21},
    'SW4': {'eq2': 0x22, 'neq2': 0x22, 'griffin': 0x22},
}

def get_channel_type_byte(command_id: str, mult_eq_type: str, is_griffin: bool = False) -> int:
    """Get channel byte for a given AVR model type."""
    entry = CHANNEL_BYTE_TABLE.get(command_id)
    if not entry:
        raise ValueError(f"Unknown channel commandId: {command_id}")

    # Griffin takes precedence if available
    if is_griffin and entry['griffin'] is not None:
        return entry['griffin']

    # XT32 uses eq2 mapping
    if mult_eq_type == 'XT32':
        if entry['eq2'] is not None:
            return entry['eq2']
        if entry['neq2'] is not None:
            return entry['neq2']

    # XT and MultEQ use neq2 mapping
    if mult_eq_type in ('XT', 'MultEQ'):
        if entry['neq2'] is not None:
            return entry['neq2']
        if entry['eq2'] is not None:
            return entry['eq2']

    # Final fallback
    if is_griffin and entry['griffin'] is not None:
        return entry['griffin']

    raise ValueError(f"No suitable channel byte mapping for {command_id}")
```

---

## 4. Sample Rate Codes Per Model

Sample rates are sent as single-byte codes in the SET_COEFDT packet header.

### transfer.js Configuration

```javascript
const TRANSFER_CONFIG = {
    sampleRates: ['00', '01', '02'],  // Used for XT32
    // ...
};
```

### Target Curves

```javascript
const TRANSFER_CONFIG = {
    targetCurves: ['00', '01'],  // '00' = Flat, '01' = Reference
};
```

### Sample Rate vs Target Curve

- **tc** (target curve): `00` = Flat, `01` = Reference
- **sr** (sample rate code): `00`, `01`, `02` for XT32

---

## 5. XT32 Filter Conversion (Polyphase Decimation)

XT32 requires special filter processing because the AVR expects a different filter length than what's in the OCA file. The `convertXT32()` function implements polyphase decimation to transform filters.

### Why Conversion is Needed

- **Speaker filters**: OCA input length = `0x3FC1` (16321 floats) → AVR expects `0x400` (1024 floats)
- **Subwoofer filters**: OCA input length = `0x3EB7` (16055 floats) → AVR expects `0x2C0` (704 floats)

### Decimation Filter Structure

```javascript
const DECIMATION_FACTOR = 4;

// Polyphase filter for subwoofer bands
const decFilterXT32Sub29_taps = [
    -0.0000068090826, -4.5359936E-8, 0.00010496614, 0.0005359394, 0.0017366897,
    0.0043950975, 0.00936928, 0.017480986, 0.029199528, 0.04430621,
    0.061674833, 0.07929655, 0.094606727, 0.1050576, 0.10877161,
    0.1050576, 0.094606727, 0.07929655, 0.061674833, 0.04430621,
    0.029199528, 0.017480986, 0.00936928, 0.0043950975, 0.0017366897,
    0.0005359394, 0.00010496614, -4.5359936E-8, -0.0000068090826
];

const decFilterXT32Sub37_taps = [
    -0.000026230078, -0.00013839548, -0.00045447858, -0.0011429883,
    -0.0023770225, -0.0042346125, -0.0065577077, -0.0088115167,
    -0.010010772, -0.008782894, -0.0036095164, 0.0067711435,
    0.02289046, 0.04414973, 0.06865209, 0.093375608, 0.11469775,
    0.12916237, 0.1342851, 0.12916237, 0.11469775, 0.093375608,
    0.06865209, 0.04414973, 0.02289046, 0.0067711435, -0.0036095164,
    -0.008782894, -0.010010772, -0.0088115167, -0.0065577077, -0.0042346125,
    -0.0023770225, -0.0011429883, -0.00045447858, -0.00013839548, -0.000026230078
];

const decFilterXT32Sub93_taps = [
    0.000004904671, 0.000016451735, 0.000035466823, 0.000054780343,
    0.000057436635, 0.000019883537, -0.00007663135, -0.00022867938,
    // ... (full 93-tap filter)
];

const decFilterXT32Sat129_taps = [
    // ... (129-tap filter for speaker channels)
];
```

### Filter Configurations

```javascript
const filterConfigs = {
    xt32Sub: {
        description: "MultEQ XT32 Subwoofer",
        inputLength: 0x3EB7,      // 16055 floats
        outputLength: 0x2C0,      // 704 floats
        bandLengths: [0x60, 0x60, 0x100, 0xEF],  // [96, 96, 256, 239]
        decFiltersInfo: [
            { phases: decomposeFilter(decFilterXT32Sub29_taps, 4), originalLength: 29 },
            { phases: decomposeFilter(decFilterXT32Sub37_taps, 4), originalLength: 37 },
            { phases: decomposeFilter(decFilterXT32Sub93_taps, 4), originalLength: 93 }
        ],
        delayComp: [true, true, true]
    },
    xt32Speaker: {
        description: "MultEQ XT32 Speaker",
        inputLength: 0x3FC1,      // 16321 floats
        outputLength: 0x400,       // 1024 floats
        bandLengths: [0x100, 0x100, 0x100, 0xEB],  // [256, 256, 256, 235]
        decFiltersInfo: [
            { phases: decomposeFilter(decFilterXT32Sat129_taps, 4), originalLength: 129 },
            { phases: decomposeFilter(decFilterXT32Sat129_taps, 4), originalLength: 129 },
            { phases: decomposeFilter(decFilterXT32Sat129_taps, 4), originalLength: 129 }
        ],
        delayComp: [true, true, true]
    }
};
```

### decomposeFilter() — Polyphase Decomposition

Breaks a filter into M phases for polyphase implementation:

```javascript
const decomposeFilter = (filterTaps, M) => {
    const L = filterTaps.length;
    if (M <= 0 || L === 0) return Array.from({ length: M || 0 }, () => []);
    const phases = Array.from({ length: M }, () => []);
    for (let p = 0; p < M; p++) {
        for (let i = 0; ; i++) {
            const n = i * M + p;
            if (n >= L) break;
            phases[p].push(filterTaps[n]);
        }
    }
    return phases;
};
```

### polyphaseDecimate() — Polyphase Decimation Operation

Performs the actual decimation using polyphase filter structure:

```javascript
const polyphaseDecimate = (signal, phases, M, originalFilterLength) => {
    const signalLen = signal.length;
    const L = originalFilterLength;
    if (signalLen === 0 || L === 0 || M <= 0 || !phases || phases.length !== M) {
        return [];
    }
    const convolvedLength = signalLen + L - 1;
    const outputLen = Math.ceil(convolvedLength / M);
    if (outputLen <= 0) return [];

    const output = new Array(outputLen).fill(0.0);

    for (let k = 0; k < outputLen; k++) {
        let y_k = 0.0;
        for (let p = 0; p < M; p++) {
            const currentPhase = phases[p];
            for (let i = 0; i < currentPhase.length; i++) {
                const inIndex = k * M + p - i * M;
                if (inIndex >= 0 && inIndex < signalLen) {
                    y_k += currentPhase[i] * signal[inIndex];
                }
            }
        }
        output[k] = y_k;
    }
    return output;
};
```

### generateWindow() — Window Function

Generates a window for band processing:

```javascript
const generateWindow = (len, type = 1) => {
    const c1 = [0.5];
    const c2 = [0.5];
    const c3 = [0.0];
    const typeIndex = type - 1;
    const a = (typeIndex >= 0 && typeIndex < c1.length) ? c1[typeIndex] : 0.5;
    const b = (typeIndex >= 0 && typeIndex < c2.length) ? c2[typeIndex] : 0.5;
    const c = (typeIndex >= 0 && typeIndex < c3.length) ? c3[typeIndex] : 0.0;

    if (len <= 0) return [];
    const window = new Array(len);
    const factor = 1.0 / (len > 1 ? len - 1 : 1);
    const pi2 = 2 * Math.PI;
    const pi4 = 4 * Math.PI;

    for (let i = 0; i < len; i++) {
        const t = i * factor;
        const cos2pit = Math.cos(pi2 * t);
        const cos4pit = Math.cos(pi4 * t);
        window[i] = a - b * cos2pit + c * cos4pit;
    }
    return window;
};
```

### calculateMultiSampleRateFilter() — Per-Band Processing

Processes one frequency band with windowing and decimation:

```javascript
const calculateMultiSampleRateFilter = (currentResidual, bandIdx, config) => {
    const bandLen = config.bandLengths[bandIdx];
    const filterInfo = config.decFiltersInfo[bandIdx];
    const useDelayComp = config.delayComp[bandIdx];

    if (!filterInfo || !filterInfo.phases || !Array.isArray(filterInfo.phases)) {
        throw new Error(`Polyphase filter info missing or invalid for band ${bandIdx}.`);
    }

    const decFilterPhases = filterInfo.phases;
    const decFilterOriginalLen = filterInfo.originalLength;

    if (bandLen <= 0) {
        return { processedBand: [], updatedResidual: [...currentResidual] };
    }

    const processedBand = new Array(bandLen).fill(0.0);
    const delay = useDelayComp ? Math.floor((decFilterOriginalLen * 3 - 3) / 2) : 0;
    const winLen = bandLen - delay;

    if (winLen < 0) {
        console.warn(`Calculated window length (${winLen}) is negative for band ${bandIdx}.`);
        return { processedBand: [], updatedResidual: [...currentResidual] };
    }

    const winAlloc = winLen * 2 + 3;
    const fullWindow = generateWindow(winAlloc, 1);

    // Copy delay portion directly
    for (let i = 0; i < delay; i++) {
        if (i < currentResidual.length) {
            processedBand[i] = currentResidual[i];
        }
    }

    // Apply window to main portion
    const windowOffset = Math.floor(winAlloc / 2) + 1;
    for (let i = 0; i < winLen; i++) {
        const residualIdx = delay + i;
        if (residualIdx < currentResidual.length && (windowOffset + i) < fullWindow.length) {
            processedBand[residualIdx] = currentResidual[residualIdx] * fullWindow[windowOffset + i];
        } else if (residualIdx >= currentResidual.length) {
            break;
        }
    }

    // Compute residual for decimation
    const residualForDecimation = [];
    for (let i = 0; i < winLen; i++) {
        const residualIdx = delay + i;
        if (residualIdx < currentResidual.length) {
            residualForDecimation.push(currentResidual[residualIdx] - processedBand[residualIdx]);
        } else {
            residualForDecimation.push(0.0);
        }
    }
    for (let i = delay + winLen; i < currentResidual.length; i++) {
        residualForDecimation.push(currentResidual[i]);
    }

    // Polyphase decimation
    const decimatedResidual = polyphaseDecimate(residualForDecimation, decFilterPhases, DECIMATION_FACTOR, decFilterOriginalLen);
    const updatedResidual = decimatedResidual.map(v => v * DECIMATION_FACTOR);

    return { processedBand, updatedResidual };
};
```

### calculateMultirate() — Full Multi-Rate Processing

Orchestrates processing across all frequency bands:

```javascript
const calculateMultirate = (impulseResponse, config) => {
    if (!impulseResponse || impulseResponse.length === 0 || !config) {
        console.error("Invalid input to calculateMultirate.");
        return [];
    }

    const finalOutput = new Array(config.outputLength).fill(0.0);
    let currentResidual = [...impulseResponse];
    let outputWriteOffset = 0;

    const numBands = config.bandLengths.length;
    const bandsToProcess = numBands - 1;

    for (let bandIdx = 0; bandIdx < bandsToProcess; bandIdx++) {
        try {
            const { processedBand, updatedResidual } = calculateMultiSampleRateFilter(
                currentResidual, bandIdx, config
            );
            const currentBandLen = config.bandLengths[bandIdx];

            for (let i = 0; i < currentBandLen; i++) {
                const outputIdx = outputWriteOffset + i;
                if (outputIdx < finalOutput.length) {
                    finalOutput[outputIdx] = (i < processedBand.length) ? processedBand[i] : 0.0;
                }
            }

            outputWriteOffset += currentBandLen;
            currentResidual = updatedResidual;
        } catch (error) {
            console.error(`Error processing band ${bandIdx}: ${error.message}`);
            throw error;
        }
    }

    // Copy last band directly (no decimation)
    const lastBandIdx = numBands - 1;
    const lastBandLen = config.bandLengths[lastBandIdx];
    for (let i = 0; i < lastBandLen; i++) {
        const outputIdx = outputWriteOffset + i;
        if (outputIdx < finalOutput.length) {
            finalOutput[outputIdx] = (i < currentResidual.length) ? currentResidual[i] : 0.0;
        }
    }

    return finalOutput;
};
```

### convertXT32() — Main Entry Point

```javascript
function convertXT32(floats) {
    const inputLength = floats ? floats.length : 0;
    if (inputLength === 0) return [];

    let configToUse = null;
    let expectedOutputLength = 0;
    let type = "Unknown";

    if (inputLength === filterConfigs.xt32Speaker.inputLength) {
        configToUse = filterConfigs.xt32Speaker;
        expectedOutputLength = filterConfigs.xt32Speaker.outputLength;
        type = "Speaker";
    } else if (inputLength === filterConfigs.xt32Sub.inputLength) {
        configToUse = filterConfigs.xt32Sub;
        expectedOutputLength = filterConfigs.xt32Sub.outputLength;
        type = "Subwoofer";
    }

    if (configToUse) {
        try {
            const mangledFilter = calculateMultirate(floats, configToUse);
            if (mangledFilter.length !== expectedOutputLength) {
                console.warn(`XT32 decimation output length (${mangledFilter.length}) != expected (${expectedOutputLength})`);
            }
            return mangledFilter;
        } catch (error) {
            console.error(`ERROR during XT32 calculateMultirate:`, error);
            return [...floats];  // Return original on error
        }
    } else {
        return [...floats];  // Return original if no config matched
    }
}
```

---

## 6. Full Transfer Sequence with Calibration State Machine

The calibration transfer follows a precise sequence of commands:

### State Machine Flow

```
DISCONNECTED
    │
    ▼
CONNECT ───────────────────────────────┐
    │                                   │
    ▼                                   │
GET_AVRINF ◄── GET_AVRSTS              │
    │                                   │
    ▼                                   │
ENTER_AUDY ◄── Calibration Mode Entry  │
    │                                   │
    ├──────────────────────┐           │
    │                       │           │
    ▼                       ▼           │
SET_SETDAT (loop)        INIT_COEFS (if fixed)
    │                       │           │
    ▼                       │           │
SET_COEFDT (loop) ◄────────┴───────────┘
    │
    ▼
FINZ_COEFS
    │
    ▼
SET_AUDYFINFLG = "Fin"
    │
    ▼
EXIT_AUDMD
    │
    ▼
DISCONNECTED
```

### Command Hex Values

| Command | Hex | Purpose |
|---------|-----|---------|
| GET_AVRINF | `54001300004745545f415652494e460000006c` | Get AVR info |
| GET_AVRSTS | `54001300004745545f41565253545300000089` | Get AVR status |
| ENTER_AUDY | `5400130000454e5445525f4155445900000077` | Enter calibration mode |
| INIT_COEFS | `5400130000494e49545f434f4546530000006a` | Initialize coefficients (fixed types only) |
| FINZ_COEFS | `540013000046494e5a5f434f4546530000006d` | Finalize coefficients |
| EXIT_AUDMD | `5400130000455849545f4155444d440000006b` | Exit calibration mode |

### buildAvrPacket() — JSON Command Builder

Used for SET_SETDAT commands with JSON payloads:

```javascript
function buildAvrPacket(commandName, jsonPayloadString, seqNum = 0, lastSeqNum = 0) {
    const commandBytes = Buffer.from(commandName, 'utf8');
    const parameterBytes = Buffer.from(jsonPayloadString, 'utf8');
    const parameterLength = parameterBytes.length;
    const commandBytesLength = commandBytes.length;

    const headerFixedOverhead = 1 + 2 + 1 + 1 + 1 + 2;  // = 8 bytes
    const totalLength = headerFixedOverhead + commandBytesLength + parameterLength + 1;

    const buffer = Buffer.alloc(totalLength);
    let offset = 0;

    buffer.writeUInt8(0x54, offset); offset += 1;                    // Marker
    buffer.writeUInt16BE(totalLength, offset); offset += 2;            // Total length
    buffer.writeUInt8(seqNum & 0xFF, offset); offset += 1;            // Sequence number
    buffer.writeUInt8(lastSeqNum & 0xFF, offset); offset += 1;         // Last sequence
    commandBytes.copy(buffer, offset); offset += commandBytes.length; // Command name
    buffer.writeUInt8(0x00, offset); offset += 1;                      // Null separator
    buffer.writeUInt16BE(parameterLength, offset); offset += 2;        // Parameter length
    parameterBytes.copy(buffer, offset); offset += parameterLength;   // JSON payload

    // Checksum
    let checksum = 0;
    for (let i = 0; i < offset; i++) {
        checksum = (checksum + buffer[i]) & 0xFF;
    }
    buffer.writeUInt8(checksum, offset);

    return buffer;
}
```

### Python Equivalent

```python
def build_avr_packet(command_name: str, json_payload: str, seq_num: int = 0, last_seq_num: int = 0) -> bytes:
    """Build an AVR packet with JSON payload."""
    command_bytes = command_name.encode('utf-8')
    parameter_bytes = json_payload.encode('utf-8')
    parameter_length = len(parameter_bytes)
    command_length = len(command_bytes)

    # Header: marker(1) + length(2) + seq(1) + last_seq(1) + command(N) + null(1) + param_len(2)
    header_fixed = 1 + 2 + 1 + 1 + command_length + 1 + 2
    total_length = header_fixed + parameter_length + 1  # +1 for checksum

    buffer = bytearray(total_length)
    offset = 0

    buffer[offset] = 0x54; offset += 1                                        # Marker
    struct.pack_into('>H', buffer, offset, total_length); offset += 2        # Total length (BE)
    buffer[offset] = seq_num & 0xFF; offset += 1                             # Sequence
    buffer[offset] = last_seq_num & 0xFF; offset += 1                        # Last sequence
    buffer[offset:offset+command_length] = command_bytes; offset += command_length
    buffer[offset] = 0x00; offset += 1                                       # Null
    struct.pack_into('>H', buffer, offset, parameter_length); offset += 2    # Parameter length (BE)
    buffer[offset:offset+parameter_length] = parameter_bytes; offset += parameter_length

    # Checksum
    checksum = sum(buffer[:offset]) & 0xFF
    buffer[offset] = checksum

    return bytes(buffer)
```

### SET_AUDYFINFLG — Final Flag Command

```javascript
// In finalizeTransfer():
const finalFlagPayload = { "AudyFinFlg": "Fin" };
const finalFlagJsonString = JSON.stringify(finalFlagPayload);
const finalFlagPacketBuffer = buildAvrPacket('SET_SETDAT', finalFlagJsonString, 0, 0);
await send(finalFlagPacketBuffer.toString('hex'), 'SET_AUDYFINFLG_FIN', {...});
```

### Python Equivalent

```python
# Final flag
final_flag_payload = {"AudyFinFlg": "Fin"}
final_flag_json = json.dumps(final_flag_payload)
final_flag_packet = build_avr_packet('SET_SETDAT', final_flag_json, 0, 0)
sock.send(final_flag_packet)
time.sleep(0.02)
# Wait for ACK...
```

---

## 7. SET_COEFDT Packet Structure

Each coefficient packet has this binary structure:

```
+--------+--------+--------+--------+--------+--------+--------+--------+
| 0x54   | Len(BE)| Seq    | Last   | SET_COEFDT (10 bytes) | 0x00   |
+--------+--------+--------+--------+--------+--------+--------+--------+
+--------+--------+  ChannelByte | SR    | Filter Data (variable)    |
+--------+--------+--------+--------+--------+--------+--------+--------+
| Checksum                                                          |
+--------+
```

### Packet Builder (generatePacketsForTransfer)

```javascript
function generatePacketsForTransfer(coeffBuffers, channelConfig, tc, sr, channelByte) {
    const packets = [];
    let floatsProcessed = 0;
    const totalFloatsToSend = coeffBuffers.length;

    for (let packetIndex = 0; packetIndex < channelConfig.packetCount; packetIndex++) {
        const isFirstPacket = packetIndex === 0;
        const isLastPacket = packetIndex === channelConfig.packetCount - 1;

        let numFloatsInPacket;
        if (isFirstPacket) {
            numFloatsInPacket = channelConfig.firstPacketFloats;  // 127
        } else if (isLastPacket) {
            numFloatsInPacket = channelConfig.lastPacketFloats;
        } else {
            numFloatsInPacket = channelConfig.midPacketFloats;  // 128
        }

        const setCoefDT_Bytes = Buffer.from('5345545f434f45464454', 'hex');  // "SET_COEFDT"

        let paramHeaderParts = [];
        if (isFirstPacket) {
            const channelByteHex = channelByte.toString(16).padStart(2, '0');
            const firstPacketInfoHex = tc + sr + channelByteHex + '00';
            paramHeaderParts.push(Buffer.from(firstPacketInfoHex, 'hex'));
        }

        const payloadCoeffsSlice = coeffBuffers.slice(floatsProcessed, floatsProcessed + numFloatsInPacket);
        const currentPayloadBuffer = Buffer.concat(payloadCoeffsSlice);
        const paramsAndDataBuffer = Buffer.concat([...paramHeaderParts, currentPayloadBuffer]);
        const paramsAndDataLength = paramsAndDataBuffer.length;

        const sizeFieldBuffer = Buffer.alloc(2);
        sizeFieldBuffer.writeUInt16BE(paramsAndDataLength, 0);

        const commandHeaderBuffer = Buffer.concat([
            setCoefDT_Bytes,
            Buffer.from([0x00]),
            sizeFieldBuffer
        ]);

        const totalPacketLengthField = 1 + 2 + 1 + 1 + commandHeaderBuffer.length + paramsAndDataBuffer.length + 1;

        const packetLengthBuffer = Buffer.alloc(2);
        packetLengthBuffer.writeUInt16BE(totalPacketLengthField, 0);

        const packetNumBuffer = Buffer.from([packetIndex & 0xFF]);
        const lastSeqNumBuffer = Buffer.from([parseInt(channelConfig.lastSequenceNumField, 16) & 0xFF]);

        const packetWithoutChecksum = Buffer.concat([
            Buffer.from([0x54]),
            packetLengthBuffer,
            packetNumBuffer,
            lastSeqNumBuffer,
            commandHeaderBuffer,
            paramsAndDataBuffer
        ]);

        // Checksum
        let checksum = 0;
        for (let i = 0; i < packetWithoutChecksum.length; i++) {
            checksum = (checksum + packetWithoutChecksum[i]) & 0xFF;
        }
        const checksumBuffer = Buffer.from([checksum]);

        const finalPacketBuffer = Buffer.concat([packetWithoutChecksum, checksumBuffer]);
        packets.push({ bufferData: finalPacketBuffer });

        floatsProcessed += numFloatsInPacket;
    }

    return packets;
}
```

### buildPacketConfig() — Calculate Packet Count

```javascript
function buildPacketConfig(totalFloats) {
    if (typeof totalFloats !== 'number' || isNaN(totalFloats) || totalFloats < 0) {
        return {
            totalFloats: 0, packetCount: 0,
            fullPacketCountField: '00', firstPacketFloats: 0,
            midPacketFloats: 128, lastPacketFloats: 0
        };
    }

    const firstPacketFloatPayload = 127;
    const midPacketFloatPayload = 128;
    let packetCount, firstPacketActualFloats, lastPacketFloats;

    if (totalFloats <= firstPacketFloatPayload) {
        packetCount = 1;
        firstPacketActualFloats = totalFloats;
        lastPacketFloats = totalFloats;
    } else {
        firstPacketActualFloats = firstPacketFloatPayload;
        const remainingFloats = totalFloats - firstPacketActualFloats;
        const numAdditionalPackets = Math.ceil(remainingFloats / midPacketFloatPayload);
        packetCount = 1 + numAdditionalPackets;
        const remainder = remainingFloats % midPacketFloatPayload;
        if (remainder === 0) {
            lastPacketFloats = midPacketFloatPayload;
        } else {
            lastPacketFloats = remainder;
        }
    }

    const lastSequenceNumber = packetCount - 1;
    const lastSequenceNumField = (lastSequenceNumber & 0xFF).toString(16).padStart(2, '0');

    return {
        totalFloats,
        packetCount,
        lastSequenceNumField,
        firstPacketFloats: firstPacketActualFloats,
        midPacketFloats: midPacketFloatPayload,
        lastPacketFloats
    };
}
```

---

## 8. processFilterDataForTransfer()

Handles model-specific filter processing before packet generation:

```javascript
function processFilterDataForTransfer(channelFilterData, multEqType, lookupChannelId) {
    let processedFilter = channelFilterData.filter || [];
    let processedFilterLV = channelFilterData.filterLV || [];

    const isSub = lookupChannelId.startsWith('SW') || lookupChannelId === 'LFE';

    if (multEqType === "XT32") {
        // Apply polyphase decimation
        processedFilter = convertXT32(processedFilter);
        processedFilterLV = convertXT32(processedFilterLV);

        const expectedLength = isSub ? filterConfigs.xt32Sub.outputLength : filterConfigs.xt32Speaker.outputLength;

        if (processedFilter.length !== expectedLength) {
            console.warn(`Post-decimation filter length for XT32 ${lookupChannelId} is ${processedFilter.length}, expected ${expectedLength}.`);
        }
    } else {
        // Non-XT32: just validate length
        let expectedLength = 0;
        if (multEqType === 'XT') {
            expectedLength = EXPECTED_NON_XT32_FLOAT_COUNTS.XT.speaker;  // 512
        } else if (multEqType === 'MultEQ') {
            expectedLength = isSub ? EXPECTED_NON_XT32_FLOAT_COUNTS.MultEQ.sub : EXPECTED_NON_XT32_FLOAT_COUNTS.MultEQ.speaker;
            // MultEQ: speaker=128, sub=512
        }
    }

    return { filter: processedFilter, filterLV: processedFilterLV };
}
```

---

## 9. Expected Float Counts Per Model

```javascript
const EXPECTED_NON_XT32_FLOAT_COUNTS = {
    'XT': { speaker: 512, sub: 512 },
    'MultEQ': { speaker: 128, sub: 512 }
};
```

---

## 10. Transfer Loop Summary

```
for (tc in targetCurves):           # ['00', '01']
    for (channel in sortedChannels):
        coeffs = (tc == '01') ? filter : filterLV
        for (sr in sampleRates):    # ['00', '01', '02'] for XT32
            packets = generatePacketsForTransfer(coeffBuffers, channelConfig, tc, sr, channelByte)
            for (packet in packets):
                send(packet)
                await ACK
```

---

_Generated from transfer.js for oca_transfer.py implementation._
