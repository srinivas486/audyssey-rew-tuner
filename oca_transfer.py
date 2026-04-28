#!/usr/bin/env python3
"""
oca_transfer.py — Transfer OCA calibration to Denon/Marantz AVR

PROTOCOL: Binary TCP on port 1256
MODEL SUPPORT: MultEQ, MultEQ XT, MultEQ XT32

Usage:
    python3 oca_transfer.py <oca_file> [AVR_IP] [--preset 1|2]
    python3 oca_transfer.py --switch-preset 1 [AVR_IP]

Model detection is automatic based on GET_AVRINF response.
XT32 filters are automatically converted using polyphase decimation.

References:
    - transfer.js (canonical implementation)
    - MODEL_GUIDE.md (detailed model handling documentation)
"""
import json
import struct
import socket
import time
import sys
import argparse
import select
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional

PORT = 1256

MARKER = 0x54

# ─── Protocol Constants ─────────────────────────────────────────────────────────

ENTER_AUDY_HEX = '5400130000454e5445525f4155445900000077'
EXIT_AUDMD_HEX = '5400130000455849545f4155444d440000006b'
FINZ_COEFS_HEX = '540013000046494e5a5f434f4546530000006d'
INIT_COEFS_HEX = '5400130000494e49545f434f4546530000006a'
GET_AVRINF_HEX = '54001300004745545f415652494e460000006c'
GET_AVRSTS_HEX = '54001300004745545f41565253545300000089'

# ─── Channel Byte Table ────────────────────────────────────────────────────────
# Maps channel IDs to byte values for different AVR model types.
# eq2: used by XT32
# neq2: used by XT and MultEQ
# griffin: used by Griffin Lite DSP (not implemented in this version)

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
    'LFE': {'eq2': 0x0d, 'neq2': 0x0d, 'griffin': 0x0d},  # LFE maps to SW1
}

# ─── Utility Functions (needed for FILTER_CONFIGS) ──────────────────────────

def decompose_filter(filter_taps: List[float], M: int) -> List[List[float]]:
    """Decompose a filter into M polyphase components."""
    L = len(filter_taps)
    if M <= 0 or L == 0:
        return [[] for _ in range(M or 0)]
    phases = [[] for _ in range(M)]
    for p in range(M):
        i = 0
        while True:
            n = i * M + p
            if n >= L:
                break
            phases[p].append(filter_taps[n])
            i += 1
    return phases


def generate_window(length: int, window_type: int = 1) -> List[float]:
    """Generate a window function."""
    c1 = [0.5]
    c2 = [0.5]
    c3 = [0.0]
    type_index = window_type - 1
    a = c1[type_index] if 0 <= type_index < len(c1) else 0.5
    b = c2[type_index] if 0 <= type_index < len(c2) else 0.5
    c = c3[type_index] if 0 <= type_index < len(c3) else 0.0
    if length <= 0:
        return []
    window = [0.0] * length
    factor = 1.0 / (length - 1 if length > 1 else 1)
    pi2 = 2 * 3.14159265359
    pi4 = 4 * 3.14159265359
    for i in range(length):
        t = i * factor
        cos2pit = math.cos(pi2 * t)
        cos4pit = math.cos(pi4 * t)
        window[i] = a - b * cos2pit + c * cos4pit
    return window


def polyphase_decimate(signal: List[float], phases: List[List[float]], M: int, original_filter_length: int) -> List[float]:
    """Perform polyphase decimation."""
    signal_len = len(signal)
    L = original_filter_length
    if signal_len == 0 or L == 0 or M <= 0 or len(phases) != M:
        return []
    convolved_length = signal_len + L - 1
    output_len = (convolved_length + M - 1) // M
    if output_len <= 0:
        return []
    output = [0.0] * output_len
    for k in range(output_len):
        y_k = 0.0
        for p in range(M):
            current_phase = phases[p]
            phase_len = len(current_phase)
            for i in range(phase_len):
                in_index = k * M + p - i * M
                if 0 <= in_index < signal_len:
                    y_k += current_phase[i] * signal[in_index]
        output[k] = y_k
    return output


# ─── XT32 Decimation Filter Coefficients ─────────────────────────────────────

DECIMATION_FACTOR = 4

# 29-tap polyphase filter for sub band 1
DEC_FILTER_XT32_SUB29_TAPS = [
    -0.0000068090826, -4.5359936E-8, 0.00010496614, 0.0005359394, 0.0017366897,
    0.0043950975, 0.00936928, 0.017480986, 0.029199528, 0.04430621,
    0.061674833, 0.07929655, 0.094606727, 0.1050576, 0.10877161,
    0.1050576, 0.094606727, 0.07929655, 0.061674833, 0.04430621,
    0.029199528, 0.017480986, 0.00936928, 0.0043950975, 0.0017366897,
    0.0005359394, 0.00010496614, -4.5359936E-8, -0.0000068090826
]

# 37-tap polyphase filter for sub band 2
DEC_FILTER_XT32_SUB37_TAPS = [
    -0.000026230078, -0.00013839548, -0.00045447858, -0.0011429883,
    -0.0023770225, -0.0042346125, -0.0065577077, -0.0088115167,
    -0.010010772, -0.008782894, -0.0036095164, 0.0067711435,
    0.02289046, 0.04414973, 0.06865209, 0.093375608, 0.11469775,
    0.12916237, 0.1342851, 0.12916237, 0.11469775, 0.093375608,
    0.06865209, 0.04414973, 0.02289046, 0.0067711435, -0.0036095164,
    -0.008782894, -0.010010772, -0.0088115167, -0.0065577077, -0.0042346125,
    -0.0023770225, -0.0011429883, -0.00045447858, -0.00013839548, -0.000026230078
]

# 93-tap polyphase filter for sub band 3
DEC_FILTER_XT32_SUB93_TAPS = [
    0.000004904671, 0.000016451735, 0.000035466823, 0.000054780343,
    0.000057436635, 0.000019883537, -0.00007663135, -0.00022867938,
    -0.0003953652, -0.0004970615, -0.00043803814, -0.00015296187,
    0.00033801072, 0.00089421676, 0.0012704487, 0.0011992522,
    0.0005233042, -0.00067407207, -0.0020127299, -0.0028939669,
    -0.0027228948, -0.0012104996, 0.0013740772, 0.004148222, 0.005850492,
    0.005338624, 0.0021824592, -0.0029139882, -0.0081179589, -0.011018342,
    -0.0096052159, -0.0033266835, 0.0062539442, 0.015607043, 0.020322932,
    0.016872915, 0.0044270838, -0.014038938, -0.031958703, -0.040876575,
    -0.033219177, -0.0052278917, 0.04104016, 0.097502038, 0.15189469,
    0.19119503, 0.20552149, 0.19119503, 0.15189469, 0.097502038,
    0.04104016, -0.0052278917, -0.033219177, -0.040876575, -0.031958703,
    -0.014038938, 0.0044270838, 0.016872915, 0.020322932, 0.015607043,
    0.0062539442, -0.0033266835, -0.0096052159, -0.011018342, -0.0081179589,
    -0.0029139882, 0.0021824592, 0.005338624, 0.005850492, 0.004148222,
    0.0013740772, -0.0012104996, -0.0027228948, -0.0028939669, -0.0020127299,
    -0.00067407207, 0.0005233042, 0.0011992522, 0.0012704487, 0.00089421676,
    0.00033801072, -0.00015296187, -0.00043803814, -0.0004970615, -0.0003953652,
    -0.00022867938, -0.00007663135, 0.000019883537, 0.000057436635,
    0.000054780343, 0.000035466823, 0.000016451735, 0.000004904671
]

# 129-tap polyphase filter for speaker bands (all 3 bands use same filter)
DEC_FILTER_XT32_SAT129_TAPS = [
    0.0000043782347, 0.000014723354, 0.000032770109, 0.000054528296,
    0.000068608439, 0.00005722275, 0.0000025561833, -0.0001022896,
    -0.00024198946, -0.0003741896, -0.0004376953, -0.00037544663,
    -0.00016613922, 0.00014951751, 0.00046477153, 0.000636138,
    0.0005427991, 0.00015503204, -0.0004217047, -0.00095836946,
    -0.0011810855, -0.00089615857, -0.00010969268, 0.0009218459,
    0.0017551293, 0.0019349628, 0.0012194271, -0.00024770317,
    -0.0019181528, -0.0030198381, -0.0028912309, -0.0013345525,
    0.0011865027, 0.0036375371, 0.0048077558, 0.0038727189,
    0.00087827817, -0.0031111876, -0.0063393954, -0.0070888256,
    -0.0045305756, 0.00070328976, 0.006557314, 0.010292898,
    0.009696761, 0.0042538098, -0.0042899773, -0.012354134,
    -0.01590999, -0.012335026, -0.0019397299, 0.0116079, 0.022352377,
    0.024387382, 0.014624386, -0.0051601734, -0.028005365, -0.043577183,
    -0.04166761, -0.016186262, 0.031879943, 0.09379751, 0.15517053,
    0.20020825, 0.21674114, 0.20020825, 0.15517053, 0.09379751,
    0.031879943, -0.016186262, -0.04166761, -0.043577183, -0.028005365,
    -0.0051601734, 0.014624386, 0.024387382, 0.022352377, 0.0116079,
    -0.0019397299, -0.012335026, -0.01590999, -0.012354134, -0.0042899773,
    0.0042538098, 0.009696761, 0.010292898, 0.006557314, 0.00070328976,
    -0.0045305756, -0.0070888256, -0.0063393954, -0.0031111876,
    0.00087827817, 0.0038727189, 0.0048077558, 0.0036375371, 0.0011865027,
    -0.0013345525, -0.0028912309, -0.0030198381, -0.0019181528,
    -0.00024770317, 0.0012194271, 0.0019349628, 0.0017551293, 0.0009218459,
    -0.00010969268, -0.00089615857, -0.0011810855, -0.00095836946,
    -0.0004217047, 0.00015503204, 0.0005427991, 0.000636138, 0.00046477153,
    0.00014951751, -0.00016613922, -0.00037544663, -0.0004376953,
    -0.0003741896, -0.00024198946, -0.0001022896, 0.0000025561833,
    0.00005722275, 0.000068608439, 0.000054528296, 0.000032770109,
    0.000014723354, 0.0000043782347
]

# XT32 filter configurations
FILTER_CONFIGS = {
    'xt32Sub': {
        'description': 'MultEQ XT32 Subwoofer',
        'input_length': 0x3EB7,   # 16055 floats
        'output_length': 0x2C0,    # 704 floats
        'band_lengths': [0x60, 0x60, 0x100, 0xEF],  # [96, 96, 256, 239]
        'dec_filters_info': [
            {'phases': decompose_filter(DEC_FILTER_XT32_SUB29_TAPS, DECIMATION_FACTOR), 'original_length': 29},
            {'phases': decompose_filter(DEC_FILTER_XT32_SUB37_TAPS, DECIMATION_FACTOR), 'original_length': 37},
            {'phases': decompose_filter(DEC_FILTER_XT32_SUB93_TAPS, DECIMATION_FACTOR), 'original_length': 93}
        ],
        'delay_comp': [True, True, True]
    },
    'xt32Speaker': {
        'description': 'MultEQ XT32 Speaker',
        'input_length': 0x3FC1,    # 16321 floats
        'output_length': 0x400,     # 1024 floats
        'band_lengths': [0x100, 0x100, 0x100, 0xEB],  # [256, 256, 256, 235]
        'dec_filters_info': [
            {'phases': decompose_filter(DEC_FILTER_XT32_SAT129_TAPS, DECIMATION_FACTOR), 'original_length': 129},
            {'phases': decompose_filter(DEC_FILTER_XT32_SAT129_TAPS, DECIMATION_FACTOR), 'original_length': 129},
            {'phases': decompose_filter(DEC_FILTER_XT32_SAT129_TAPS, DECIMATION_FACTOR), 'original_length': 129}
        ],
        'delay_comp': [True, True, True]
    }
}

# Expected filter lengths for non-XT32 models
EXPECTED_NON_XT32_FLOAT_COUNTS = {
    'XT': {'speaker': 512, 'sub': 512},
    'MultEQ': {'speaker': 128, 'sub': 512}
}

# ─── Utility Functions ─────────────────────────────────────────────────────────

def detect_mult_eq_type(eq_type_str: str) -> str:
    """Detect MultEQ type from EQType string in GET_AVRINF response."""
    if eq_type_str is None:
        return 'MultEQ'
    if 'XT32' in eq_type_str:
        return 'XT32'
    elif 'XT' in eq_type_str:
        return 'XT'
    else:
        return 'MultEQ'


def get_channel_type_byte(command_id: str, mult_eq_type: str, is_griffin: bool = False) -> int:
    """Get channel byte for a given AVR model type.

    XT32 uses eq2 mapping.
    XT and MultEQ use neq2 mapping.
    Griffin Lite DSP uses griffin mapping when available.
    """
    entry = CHANNEL_BYTE_TABLE.get(command_id)
    if entry is None:
        raise ValueError(f"Unknown channel commandId: {command_id}")

    # Griffin takes precedence if available and requested
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

    # Final fallback to griffin if available
    if is_griffin and entry['griffin'] is not None:
        return entry['griffin']

    raise ValueError(f"No suitable channel byte mapping for {command_id}")


def java_float_to_fixed32bits(f: float) -> int:
    """Convert float to AVR fixed-point 32-bit representation.

    This matches the javaFloatToFixed32bits() function in transfer.js.
    The AVR uses a special fixed-point format for coefficients on
    certain models (those reporting DType starting with 'fixed').
    """
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
                f2 -= 1.0

    if is_negative:
        result_int = (~result_int) & 0xFFFFFFFF | 0x80000000

    # Ensure we return a signed 32-bit integer
    if result_int >= 0x80000000:
        result_int -= 0x100000000

    return result_int


def decompose_filter(filter_taps: List[float], M: int) -> List[List[float]]:
    """Decompose a filter into M polyphase components.

    This matches the decomposeFilter() function in transfer.js.
    """
    L = len(filter_taps)
    if M <= 0 or L == 0:
        return [[] for _ in range(M or 0)]

    phases = [[] for _ in range(M)]
    for p in range(M):
        i = 0
        while True:
            n = i * M + p
            if n >= L:
                break
            phases[p].append(filter_taps[n])
            i += 1

    return phases


def polyphase_decimate(signal: List[float], phases: List[List[float]], M: int, original_filter_length: int) -> List[float]:
    """Perform polyphase decimation.

    This matches the polyphaseDecimate() function in transfer.js.
    """
    signal_len = len(signal)
    L = original_filter_length

    if signal_len == 0 or L == 0 or M <= 0 or len(phases) != M:
        return []

    convolved_length = signal_len + L - 1
    output_len = (convolved_length + M - 1) // M

    if output_len <= 0:
        return []

    output = [0.0] * output_len

    for k in range(output_len):
        y_k = 0.0
        for p in range(M):
            current_phase = phases[p]
            phase_len = len(current_phase)
            for i in range(phase_len):
                in_index = k * M + p - i * M
                if 0 <= in_index < signal_len:
                    y_k += current_phase[i] * signal[in_index]
        output[k] = y_k

    return output


def generate_window(length: int, window_type: int = 1) -> List[float]:
    """Generate a window function.

    This matches the generateWindow() function in transfer.js.
    """
    c1 = [0.5]
    c2 = [0.5]
    c3 = [0.0]

    type_index = window_type - 1
    a = c1[type_index] if 0 <= type_index < len(c1) else 0.5
    b = c2[type_index] if 0 <= type_index < len(c2) else 0.5
    c = c3[type_index] if 0 <= type_index < len(c3) else 0.0

    if length <= 0:
        return []

    window = [0.0] * length
    factor = 1.0 / (length - 1 if length > 1 else 1)
    pi2 = 2 * 3.14159265359
    pi4 = 4 * 3.14159265359

    for i in range(length):
        t = i * factor
        cos2pit = math.cos(pi2 * t)
        cos4pit = math.cos(pi4 * t)
        window[i] = a - b * cos2pit + c * cos4pit

    return window


import math


def calculate_multi_sample_rate_filter(current_residual: List[float], band_idx: int, config: dict) -> Tuple[List[float], List[float]]:
    """Process one frequency band with windowing and decimation.

    This matches the calculateMultiSampleRateFilter() function in transfer.js.
    """
    import math

    band_lengths = config['band_lengths']
    dec_filters_info = config['dec_filters_info']
    delay_comp = config['delay_comp']

    band_len = band_lengths[band_idx]
    filter_info = dec_filters_info[band_idx]
    use_delay_comp = delay_comp[band_idx]

    dec_filter_phases = filter_info['phases']
    dec_filter_original_len = filter_info['original_length']

    if band_len <= 0:
        return [], list(current_residual)

    processed_band = [0.0] * band_len
    delay = math.floor((dec_filter_original_len * 3 - 3) / 2) if use_delay_comp else 0
    win_len = band_len - delay

    if win_len < 0:
        return [], list(current_residual)

    win_alloc = win_len * 2 + 3
    full_window = generate_window(win_alloc, 1)

    # Copy delay portion directly
    for i in range(delay):
        if i < len(current_residual):
            processed_band[i] = current_residual[i]

    # Apply window to main portion
    window_offset = math.floor(win_alloc / 2) + 1
    for i in range(win_len):
        residual_idx = delay + i
        if residual_idx < len(current_residual) and (window_offset + i) < len(full_window):
            processed_band[residual_idx] = current_residual[residual_idx] * full_window[window_offset + i]
        elif residual_idx >= len(current_residual):
            break

    # Compute residual for decimation
    residual_for_decimation = []
    for i in range(win_len):
        residual_idx = delay + i
        if residual_idx < len(current_residual):
            residual_for_decimation.append(current_residual[residual_idx] - processed_band[residual_idx])
        else:
            residual_for_decimation.append(0.0)

    for i in range(delay + win_len, len(current_residual)):
        residual_for_decimation.append(current_residual[i])

    # Polyphase decimation
    decimated_residual = polyphase_decimate(residual_for_decimation, dec_filter_phases, DECIMATION_FACTOR, dec_filter_original_len)
    updated_residual = [v * DECIMATION_FACTOR for v in decimated_residual]

    return processed_band, updated_residual


def calculate_multirate(impulse_response: List[float], config: dict) -> List[float]:
    """Orchestrate processing across all frequency bands.

    This matches the calculateMultirate() function in transfer.js.
    """
    import math

    if not impulse_response or len(impulse_response) == 0:
        return []

    output_length = config['output_length']
    final_output = [0.0] * output_length
    current_residual = list(impulse_response)
    output_write_offset = 0

    num_bands = len(config['band_lengths'])
    bands_to_process = num_bands - 1

    for band_idx in range(bands_to_process):
        processed_band, current_residual = calculate_multi_sample_rate_filter(
            current_residual, band_idx, config
        )
        current_band_len = config['band_lengths'][band_idx]

        for i in range(current_band_len):
            output_idx = output_write_offset + i
            if output_idx < output_length and i < len(processed_band):
                final_output[output_idx] = processed_band[i]

        output_write_offset += current_band_len

    # Copy last band directly (no decimation)
    last_band_idx = num_bands - 1
    last_band_len = config['band_lengths'][last_band_idx]
    for i in range(last_band_len):
        output_idx = output_write_offset + i
        if output_idx < output_length and i < len(current_residual):
            final_output[output_idx] = current_residual[i]

    return final_output


def convert_xt32(floats: List[float]) -> List[float]:
    """Apply XT32 polyphase decimation to filter coefficients.

    This matches the convertXT32() function in transfer.js.

    Speaker filters: input 0x3FC1 (16321 floats) -> output 0x400 (1024 floats)
    Sub filters: input 0x3EB7 (16055 floats) -> output 0x2C0 (704 floats)
    """
    input_length = len(floats)
    if input_length == 0:
        return []

    config_to_use = None
    expected_output_length = 0
    filter_type = "Unknown"

    if input_length == FILTER_CONFIGS['xt32Speaker']['input_length']:
        config_to_use = FILTER_CONFIGS['xt32Speaker']
        expected_output_length = FILTER_CONFIGS['xt32Speaker']['output_length']
        filter_type = "Speaker"
    elif input_length == FILTER_CONFIGS['xt32Sub']['input_length']:
        config_to_use = FILTER_CONFIGS['xt32Sub']
        expected_output_length = FILTER_CONFIGS['xt32Sub']['output_length']
        filter_type = "Subwoofer"

    if config_to_use:
        try:
            mangled_filter = calculate_multirate(floats, config_to_use)
            if len(mangled_filter) != expected_output_length:
                print(f"  WARNING: XT32 decimation output length ({len(mangled_filter)}) != expected ({expected_output_length})")
            return mangled_filter
        except Exception as e:
            print(f"  ERROR during XT32 decimation: {e}")
            return list(floats)  # Return original on error
    else:
        return list(floats)  # Return original if no config matched


def process_filter_data_for_transfer(channel_filter_data: dict, mult_eq_type: str, lookup_channel_id: str) -> Tuple[List[float], List[float]]:
    """Process filter data according to model type.

    For XT32, applies polyphase decimation.
    For XT and MultEQ, returns filters as-is (with length validation).
    """
    processed_filter = channel_filter_data.get('filter', [])
    processed_filter_lv = channel_filter_data.get('filterLV', [])

    is_sub = lookup_channel_id.startswith('SW') or lookup_channel_id == 'LFE'

    if mult_eq_type == 'XT32':
        # Apply polyphase decimation for XT32
        processed_filter = convert_xt32(processed_filter)
        processed_filter_lv = convert_xt32(processed_filter_lv)

        expected_length = FILTER_CONFIGS['xt32Sub']['output_length'] if is_sub else FILTER_CONFIGS['xt32Speaker']['output_length']

        if len(processed_filter) != expected_length:
            print(f"  WARNING: Post-decimation filter length for XT32 {lookup_channel_id} is {len(processed_filter)}, expected {expected_length}")
        if len(processed_filter_lv) != expected_length:
            print(f"  WARNING: Post-decimation filterLV length for XT32 {lookup_channel_id} is {len(processed_filter_lv)}, expected {expected_length}")
    else:
        # Non-XT32: validate length
        expected_length = 0
        if mult_eq_type == 'XT':
            expected_length = EXPECTED_NON_XT32_FLOAT_COUNTS['XT']['speaker'] if not is_sub else EXPECTED_NON_XT32_FLOAT_COUNTS['XT']['sub']
        elif mult_eq_type == 'MultEQ':
            expected_length = EXPECTED_NON_XT32_FLOAT_COUNTS['MultEQ']['speaker'] if not is_sub else EXPECTED_NON_XT32_FLOAT_COUNTS['MultEQ']['sub']

        if expected_length > 0:
            if len(processed_filter) != expected_length:
                print(f"  WARNING: Input filter length for {mult_eq_type} {lookup_channel_id} is {len(processed_filter)}, expected {expected_length}")

    return processed_filter, processed_filter_lv


def build_packet_config(total_floats: int) -> dict:
    """Calculate packet configuration for coefficient transfer.

    This matches the buildPacketConfig() function in transfer.js.

    Returns:
        dict with packetCount, lastSequenceNumField, firstPacketFloats,
        midPacketFloats, lastPacketFloats
    """
    if total_floats <= 0:
        return {
            'totalFloats': 0,
            'packetCount': 0,
            'lastSequenceNumField': '00',
            'firstPacketFloats': 0,
            'midPacketFloats': 128,
            'lastPacketFloats': 0
        }

    first_packet_float_payload = 127
    mid_packet_float_payload = 128

    if total_floats <= first_packet_float_payload:
        packet_count = 1
        first_packet_actual_floats = total_floats
        last_packet_floats = total_floats
    else:
        first_packet_actual_floats = first_packet_float_payload
        remaining_floats = total_floats - first_packet_actual_floats
        num_additional_packets = (remaining_floats + mid_packet_float_payload - 1) // mid_packet_float_payload
        packet_count = 1 + num_additional_packets
        remainder = remaining_floats % mid_packet_float_payload
        if remainder == 0:
            last_packet_floats = mid_packet_float_payload
        else:
            last_packet_floats = remainder

    last_sequence_number = packet_count - 1
    last_sequence_num_field = format(last_sequence_number & 0xFF, '02x')

    return {
        'totalFloats': total_floats,
        'packetCount': packet_count,
        'lastSequenceNumField': last_sequence_num_field,
        'firstPacketFloats': first_packet_actual_floats,
        'midPacketFloats': mid_packet_float_payload,
        'lastPacketFloats': last_packet_floats
    }


def build_avr_packet(command_name: str, json_payload: str, seq_num: int = 0, last_seq_num: int = 0) -> bytes:
    """Build an AVR packet with JSON payload.

    This matches the buildAvrPacket() function in transfer.js.

    Packet structure:
        0x54 (1 byte) - Marker
        Total length (2 bytes, big-endian)
        Sequence number (1 byte)
        Last sequence number (1 byte)
        Command name (variable)
        0x00 (1 byte) - Null separator
        Parameter length (2 bytes, big-endian)
        Parameter data (JSON payload)
        Checksum (1 byte)
    """
    command_bytes = command_name.encode('utf-8')
    parameter_bytes = json_payload.encode('utf-8')
    parameter_length = len(parameter_bytes)
    command_length = len(command_bytes)

    # Header: marker(1) + length(2) + seq(1) + last_seq(1) + command(N) + null(1) + param_len(2)
    header_fixed = 1 + 2 + 1 + 1 + command_length + 1 + 2
    total_length = header_fixed + parameter_length + 1  # +1 for checksum

    buffer = bytearray(total_length)
    offset = 0

    buffer[offset] = MARKER; offset += 1
    struct.pack_into('>H', buffer, offset, total_length); offset += 2
    buffer[offset] = seq_num & 0xFF; offset += 1
    buffer[offset] = last_seq_num & 0xFF; offset += 1
    buffer[offset:offset+command_length] = command_bytes; offset += command_length
    buffer[offset] = 0x00; offset += 1
    struct.pack_into('>H', buffer, offset, parameter_length); offset += 2
    buffer[offset:offset+parameter_length] = parameter_bytes; offset += parameter_length

    # Checksum
    checksum = sum(buffer[:offset]) & 0xFF
    buffer[offset] = checksum

    return bytes(buffer)


def generate_coef_packets(coeff_buffers: List[bytes], channel_config: dict, tc: str, sr: str, channel_byte: int) -> List[bytes]:
    """Generate SET_COEFDT packets for coefficient transfer.

    This matches the generatePacketsForTransfer() function in transfer.js.
    """
    packets = []
    floats_processed = 0
    total_floats_to_send = len(coeff_buffers)

    set_coef_dt_bytes = bytes([0x53, 0x45, 0x54, 0x5f, 0x43, 0x4f, 0x45, 0x46, 0x44, 0x54])  # "SET_COEFDT"

    for packet_index in range(channel_config['packetCount']):
        is_first_packet = packet_index == 0
        is_last_packet = packet_index == channel_config['packetCount'] - 1

        if is_first_packet:
            num_floats_in_packet = channel_config['firstPacketFloats']
        elif is_last_packet:
            num_floats_in_packet = channel_config['lastPacketFloats']
        else:
            num_floats_in_packet = channel_config['midPacketFloats']

        if num_floats_in_packet <= 0:
            continue

        if floats_processed >= total_floats_to_send:
            break

        if floats_processed + num_floats_in_packet > total_floats_to_send:
            num_floats_in_packet = total_floats_to_send - floats_processed

        param_header_parts = []
        if is_first_packet:
            # First packet includes: tc + sr + channel_byte + 0x00
            channel_byte_hex = format(channel_byte, '02x')
            first_packet_info = bytes.fromhex(tc + sr + channel_byte_hex + '00')
            param_header_parts.append(first_packet_info)

        # Extract coefficient buffers for this packet
        payload_coeffs_slice = coeff_buffers[floats_processed:floats_processed + num_floats_in_packet]
        current_payload_buffer = b''.join(payload_coeffs_slice)

        params_and_data_buffer = b''.join(param_header_parts) + current_payload_buffer
        params_and_data_length = len(params_and_data_buffer)

        # Build command header: SET_COEFDT + 0x00 + size (2 bytes BE)
        size_field = struct.pack('>H', params_and_data_length)
        command_header = set_coef_dt_bytes + bytes([0x00]) + size_field

        # Total packet length
        total_packet_length = 1 + 2 + 1 + 1 + len(command_header) + params_and_data_length + 1
        # = marker + length + seq + last_seq + header + data + checksum

        packet_length_buffer = struct.pack('>H', total_packet_length)
        packet_num_buffer = bytes([packet_index & 0xFF])
        last_seq_num_buffer = bytes([int(channel_config['lastSequenceNumField'], 16) & 0xFF])

        # Build packet without checksum
        packet_without_checksum = (
            bytes([MARKER]) +
            packet_length_buffer +
            packet_num_buffer +
            last_seq_num_buffer +
            command_header +
            params_and_data_buffer
        )

        # Calculate checksum
        checksum = sum(packet_without_checksum) & 0xFF
        final_packet = packet_without_checksum + bytes([checksum])

        packets.append(final_packet)
        floats_processed += num_floats_in_packet

    return packets


# ─── Communication Helpers ──────────────────────────────────────────────────────

def send_raw(sock: socket.socket, data: bytes, timeout: float = 5.0) -> bool:
    """Send raw bytes and wait for ACK."""
    sock.settimeout(timeout)
    sock.send(data)
    try:
        resp = sock.recv(4096)
        return b'ACK' in resp or b'ack' in resp
    except socket.timeout:
        return False


def send_and_wait_ack(sock: socket.socket, data: bytes, timeout: float = 5.0) -> bool:
    """Send data and return True if ACK received."""
    sock.settimeout(timeout)
    try:
        sock.send(data)
        time.sleep(0.02)  # Small delay per transfer.js
        resp = b''
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp += chunk
            except socket.timeout:
                break
            if b'ACK' in resp or b'NACK' in resp or b'NAK' in resp:
                break
        return b'ACK' in resp
    except Exception as e:
        print(f"Send error: {e}")
        return False


def receive_json_response(sock: socket.socket, timeout: float = 5.0) -> Optional[dict]:
    """Receive and parse JSON response from AVR."""
    sock.settimeout(timeout)
    resp = b''
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b'}' in chunk:
                break
    except socket.timeout:
        pass

    if resp and resp[0] == MARKER:
        ascii_str = resp.decode('ascii', errors='replace')
        bp = ascii_str.find('{')
        be = ascii_str.rfind('}')
        if bp >= 0 and be >= bp:
            try:
                return json.loads(ascii_str[bp:be+1])
            except json.JSONDecodeError:
                pass
    return None


# ─── Preset Switch ─────────────────────────────────────────────────────────────

def switch_preset(ip: str, preset: str):
    """Switch Audyssey preset on AVR via Telnet (SPPR command)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    sock.connect((ip, 23))
    time.sleep(0.3)
    try:
        sock.recv(4096)  # drain banner
    except:
        pass

    # Query current preset
    sock.send(b'SPPR ?\r')
    time.sleep(0.2)
    resp = b''
    while True:
        readable, _, _ = select.select([sock], [], [], 1)
        if readable:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk
        else:
            break
    current = resp.decode('ascii', errors='replace').strip()
    print(f"Current preset: {current}")

    # Set target preset
    sock.send(f'SPPR {preset}\r'.encode())
    time.sleep(0.3)
    resp = b''
    while True:
        readable, _, _ = select.select([sock], [], [], 1)
        if readable:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk
        else:
            break
    print(f"Switched to preset {preset}")
    sock.close()


# ─── Telnet Command Helpers (shared low-level primitive) ─────────────────────

def _telnet_send_command(ip: str, command: str, timeout: float = 3.0) -> str:
    """Low-level helper: send a Telnet command and return the response line.

    Connects to port 23, sends command+\r, reads one line response.
    Used as building block for all Telnet-based functions.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((ip, 23))
    time.sleep(0.1)
    try:
        sock.recv(4096)  # drain banner on connect
    except socket.timeout:
        pass

    sock.send(command.encode('ascii') + b'\r')
    resp = b''
    while True:
        readable, _, _ = select.select([sock], [], [], timeout)
        if readable:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk
        else:
            break
    sock.close()
    return resp.decode('ascii', errors='replace').strip()


# ─── Power Commands (Telnet port 23) ─────────────────────────────────────────

def get_power_status(ip: str) -> str:
    """Query AVR power status via ZM? command.

    Returns 'ON', 'OFF', or 'UNKNOWN' if the response cannot be parsed.
    """
    response = _telnet_send_command(ip, 'ZM?')
    upper = response.upper()
    if 'ZMON' in upper:
        return 'ON'
    elif 'ZMOFF' in upper:
        return 'OFF'
    return 'UNKNOWN'


def power_on(ip: str) -> bool:
    """Turn AVR on via ZMON command, then verify with ZM?.

    Waits 5 seconds after ZMON before checking status.
    Returns True if the AVR confirms ON state.
    """
    _telnet_send_command(ip, 'ZMON')
    # Wait for AVR to boot up
    time.sleep(5.0)
    status = get_power_status(ip)
    return status == 'ON'


def power_off(ip: str) -> bool:
    """Turn AVR off via ZMOFF command.

    Returns True if command was sent successfully (no error).
    """
    try:
        _telnet_send_command(ip, 'ZMOFF')
        return True
    except Exception:
        return False


# ─── Subwoofer / Bass / LFE Commands (Telnet port 23) ─────────────────────────

def set_subwoofer_level_off(ip: str) -> bool:
    """Send PSSWL OFF twice (for old model types).

    Older Denon/Marantz AVRs use PSSWL OFF to disable the subwoofer level.
    The command is sent twice per transfer.js behavior.
    """
    try:
        _telnet_send_command(ip, 'PSSWL OFF')
        time.sleep(0.75)
        _telnet_send_command(ip, 'PSSWL OFF')
        return True
    except Exception:
        return False


def set_bass_mode(ip: str, mode: str, is_new_model: bool = False) -> bool:
    """Set bass mode (LFE, L+M, etc.) via SSMWM or SSSWO.

    Args:
        ip: AVR IP address.
        mode: Bass mode string, e.g. 'LFE', 'L+M'.
        is_new_model: If False (old models), use SSMWM. If True, use SSSWO.

    Sends the command twice per transfer.js behavior.
    """
    try:
        if not is_new_model:
            cmd = f'SSMWM {mode.upper()}'
        else:
            cmd = f'SSSWO {mode.upper()}'
        _telnet_send_command(ip, cmd)
        time.sleep(0.75)
        _telnet_send_command(ip, cmd)
        return True
    except Exception:
        return False


def set_lpf_for_lfe(ip: str, freq: int) -> bool:
    """Set LPF (Low-Pass Filter) for LFE channel via SSLFL.

    Args:
        ip: AVR IP address.
        freq: Crossover frequency in Hz (e.g. 120).

    The frequency is zero-padded to 3 digits for the command.
    Sent twice per transfer.js behavior.
    """
    try:
        freq_str = str(freq).zfill(3)
        cmd = f'SSLFL {freq_str}'
        _telnet_send_command(ip, cmd)
        time.sleep(0.75)
        _telnet_send_command(ip, cmd)
        return True
    except Exception:
        return False


def set_front_speaker_bass_extraction(ip: str, freq: int) -> bool:
    """Enable front-speaker full-range + set bass extraction frequency.
    Only supported on newer AVR models.
    Sequence:
        1. SSCFRFRO FUL  (x2) - set front speakers to full range
        2. SSBELFRO {freq:03d}  (x2) - set bass extraction frequency

    Args:
        ip: AVR IP address.
        freq: Bass extraction crossover frequency in Hz (e.g. 80).

    Returns True if all commands succeeded.
    """
    try:
        freq_str = str(freq).zfill(3)
        # Set front speakers to full range
        _telnet_send_command(ip, 'SSCFRFRO FUL')
        time.sleep(0.75)
        _telnet_send_command(ip, 'SSCFRFRO FUL')
        time.sleep(0.75)
        # Set bass extraction frequency
        _telnet_send_command(ip, f'SSBELFRO {freq_str}')
        time.sleep(0.75)
        _telnet_send_command(ip, f'SSBELFRO {freq_str}')
        return True
    except Exception:
        return False


# ─── HTTP Model Discovery ─────────────────────────────────────────────────────

def discover_model_via_http(ip: str) -> Optional[str]:
    """Fetch model name from AVR via HTTP /goform endpoint.

    Queries http://<ip>/goform/formMainZone_MainZoneXml.xml and extracts
    the <ModelName> or <FriendlyName> value.

    Returns the model name string, or None if the endpoint is unreachable
    or the name cannot be determined.
    """
    import re
    import urllib.request
    import urllib.error

    url = f'http://{ip}/goform/formMainZone_MainZoneXml.xml'
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status != 200:
                return None
            content = resp.read().decode('utf-8', errors='replace')

        # Extract <ModelName><value>...</value></ModelName>
        model_match = re.search(
            r'<ModelName>\s*<value>(.*?)</value>\s*</ModelName>', content, re.IGNORECASE
        )
        friendly_match = re.search(
            r'<FriendlyName>\s*<value>(.*?)</value>\s*</FriendlyName>', content, re.IGNORECASE
        )
        model_name = model_match.group(1).strip() if model_match else None
        friendly_name = friendly_match.group(1).strip() if friendly_match else None

        # Reject generic placeholder names
        generic_pattern = re.compile(
            r'receiver|network\s*(audio|av)|(av|media)\s*(server|renderer|player)',
            re.IGNORECASE
        )

        if model_name and not generic_pattern.search(model_name):
            return model_name
        if friendly_name and not generic_pattern.search(friendly_name):
            return friendly_name
        return None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


# ─── SET_SETDAT Command Builder ───────────────────────────────────────────────

def map_channel_id_for_setdat(channel_id: str) -> str:
    """Map OCA channel IDs to AVR-recognized IDs.

    This matches the mapChannelIdForSetDat() function in transfer.js.
    """
    mapping = {
        'SWLFE': 'SW1',
        'SWLFE2SP': 'SW1',
        'SWLEFT2SP': 'SW1',
        'SWRIGHT2SP': 'SW2',
        'SWFRONT2SP': 'SW1',
        'SWBACK2SP': 'SW2',
        'SWLFE3SP': 'SW1',
        'SWLEFT3SP': 'SW1',
        'SWRIGHT3SP': 'SW2',
        'SWFRONTLEFT3SP': 'SW1',
        'SWFRONTRIGHT3SP': 'SW2',
        'SWREAR3SP': 'SW3',
        'SWLFE4SP': 'SW1',
        'SWFRONTLEFT4SP': 'SW1',
        'SWFRONTRIGHT4SP': 'SW2',
        'SWBACKLEFT4SP': 'SW3',
        'SWBACKRIGHT4SP': 'SW4',
        'SWMIX1': 'SW1',
        'SWMIX2': 'SW2',
        'SWMIX3': 'SW3',
        'SWMIX4': 'SW4',
    }
    return mapping.get(channel_id, channel_id)


def build_set_dat_params(avr_status: dict, raw_ch_setup: List[dict], filter_data: dict,
                          sorted_channel_info: List[dict], mult_eq_type: str) -> List[dict]:
    """Build ordered parameter list for SET_SETDAT command.

    This matches the prepareParamsInOrder() function in transfer.js.
    """
    params = []

    # Parameters to send in order
    df_setting_data_parameters = [
        "AmpAssign", "AssignBin", "SpConfig", "Distance", "ChLevel", "Crossover",
        "AudyFinFlg", "AudyDynEq", "AudyEqRef", "AudyDynVol", "AudyDynSet",
        "AudyMultEQ", "AudyEqSet", "AudyLfc", "AudyLfcLev", "SWSetup"
    ]

    source_amp_assign = avr_status.get('AmpAssign')
    source_assign_bin = avr_status.get('AssignBin')

    if not source_amp_assign or not source_assign_bin:
        raise ValueError("AmpAssign or AssignBin missing from AVR Status")

    # Calibration settings
    calibration_settings = {
        "AudyFinFlg": "NotFin",
        "AudyDynEq": False,
        "AudyEqRef": 0,
        "AudyDynVol": False,
        "AudyDynSet": "L",
        "AudyMultEQ": True,
        "AudyEqSet": "Flat",
        "AudyLfc": False,
        "AudyLfcLev": 3
    }

    # Build SpConfig, Distance, ChLevel, Crossover arrays
    final_sp_config = []
    distance_array = []
    ch_level_array = []
    crossover_array = []
    sub_setup = None

    # Check for SWSetup
    sw_setup = avr_status.get('SWSetup')
    if sw_setup and isinstance(sw_setup, dict) and sw_setup.get('SWNum') is not None:
        sw_num = int(sw_setup['SWNum'], 10)
        if not is_naN(sw_num) and sw_num > 0:
            sub_setup = {"SWNum": sw_num, "SWMode": "Standard", "SWLayout": "N/A"}

    for channel_info in sorted_channel_info:
        avr_original_channel_id = channel_info['id']
        avr_mapped_channel_id = channel_info['mappedId']

        # Find AVR setup entry
        avr_setup_entry = None
        for entry in raw_ch_setup:
            if list(entry.keys())[0] == avr_original_channel_id:
                avr_setup_entry = entry
                break

        if not avr_setup_entry:
            raise ValueError(f"Could not find setup entry for channel {avr_original_channel_id}")

        avr_reported_speaker_type = avr_setup_entry[avr_original_channel_id]

        # Find OCA channel data
        oca_channel = None
        for ch in filter_data.get('channels', []):
            mapped_id = map_channel_id_for_setdat(ch.get('commandId', ''))
            if mapped_id == avr_mapped_channel_id:
                oca_channel = ch
                break

        if not oca_channel:
            raise ValueError(f"Channel {avr_mapped_channel_id} not found in OCA file")

        oca_speaker_type = oca_channel.get('speakerType', 'S')
        final_sp_config.append({avr_mapped_channel_id: oca_speaker_type})

        # Distance
        dist_meters = oca_channel.get('distanceInMeters')
        if dist_meters is not None:
            distance_array.append({avr_mapped_channel_id: int(dist_meters * 100)})

        # Trim
        trim_db = oca_channel.get('trimAdjustmentInDbs')
        if trim_db is not None:
            ch_level_array.append({avr_mapped_channel_id: int(trim_db * 10)})

        # Crossover
        is_subwoofer = oca_speaker_type == 'E'
        is_large = oca_speaker_type == 'L'

        if is_subwoofer or is_large:
            crossover_array.append({avr_mapped_channel_id: "F"})
        else:
            xover = oca_channel.get('xover')
            if xover is not None:
                if isinstance(xover, str) and xover.upper() == 'F':
                    print(f"Warning: Speaker {avr_mapped_channel_id} specified with 'F' crossover but type is 'S'")
                else:
                    crossover_array.append({avr_mapped_channel_id: int(xover)})

    # Build final params list
    param_values = {
        "AmpAssign": source_amp_assign,
        "AssignBin": source_assign_bin,
        "SpConfig": final_sp_config if final_sp_config else None,
        "Distance": distance_array if distance_array else None,
        "ChLevel": ch_level_array if ch_level_array else None,
        "Crossover": crossover_array if crossover_array else None,
        "AudyFinFlg": calibration_settings["AudyFinFlg"],
        "AudyDynEq": calibration_settings["AudyDynEq"],
        "AudyEqRef": calibration_settings["AudyEqRef"],
        "AudyDynVol": calibration_settings["AudyDynVol"],
        "AudyDynSet": calibration_settings["AudyDynSet"],
        "AudyMultEQ": calibration_settings["AudyMultEQ"],
        "AudyEqSet": calibration_settings["AudyEqSet"],
        "AudyLfc": calibration_settings["AudyLfc"],
        "AudyLfcLev": calibration_settings["AudyLfcLev"],
        "SWSetup": sub_setup
    }

    for key in df_setting_data_parameters:
        value = param_values.get(key)
        if value is not None:
            params.append({'key': key, 'value': value})

    return params


def send_set_dat_command(sock: socket.socket, avr_status: dict, raw_ch_setup: List[dict],
                         filter_data: dict, sorted_channel_info: List[dict],
                         mult_eq_type: str, has_griffin_lite_dsp: bool = False):
    """Send SET_SETDAT command with all parameters.

    This matches the sendSetDatCommand() function in transfer.js.
    """
    BINARY_PACKET_THRESHOLD = 510

    ordered_params = build_set_dat_params(
        avr_status, raw_ch_setup, filter_data, sorted_channel_info, mult_eq_type
    )

    if not ordered_params:
        print("No parameters generated for SET_SETDAT. Skipping.")
        return

    # Build JSON packets (chunking if needed)
    packets_json_strings = []
    current_packet_payload = {}

    for param_info in ordered_params:
        param_key = param_info['key']
        param_value = param_info['value']

        test_packet_payload = dict(current_packet_payload)
        test_packet_payload[param_key] = param_value

        try:
            test_json_string = json.dumps(test_packet_payload)
            test_buffer = build_avr_packet('SET_SETDAT', test_json_string, 0, 0)
        except Exception as e:
            print(f"Error building test packet for {param_key}: {e}")
            raise

        if len(test_buffer) > BINARY_PACKET_THRESHOLD:
            if current_packet_payload:
                packets_json_strings.append(json.dumps(current_packet_payload))
            else:
                raise ValueError(f"Parameter {param_key} alone exceeds threshold")

            current_packet_payload = {param_key: param_value}
            single_param_json = json.dumps(current_packet_payload)
            single_param_buffer = build_avr_packet('SET_SETDAT', single_param_json, 0, 0)

            if len(single_param_buffer) > BINARY_PACKET_THRESHOLD:
                raise ValueError(f"Single parameter {param_key} still exceeds threshold")
        else:
            current_packet_payload[param_key] = param_value

    if current_packet_payload:
        packets_json_strings.append(json.dumps(current_packet_payload))

    # Send packets
    for i, json_string in enumerate(packets_json_strings):
        packet_buffer = build_avr_packet('SET_SETDAT', json_string, 0, 0)
        label = f"SET_SETDAT Pkt {i + 1}/{len(packets_json_strings)}"

        ack = send_and_wait_ack(sock, packet_buffer)
        if not ack:
            print(f"WARNING: No ACK for {label}")
        else:
            print(f"  ACK: {label}")

    time.sleep(0.02)


# ─── Main Transfer Function ─────────────────────────────────────────────────────

def transfer(oca_path: Path, ip: str, preset: str = '1'):
    """Execute the full OCA calibration transfer."""
    import math

    print(f"=== OCA Transfer ===")
    print(f"File: {oca_path.name}")
    print(f"Target: {ip}:{PORT}")
    print(f"Preset: {preset} (Audyssey slot)\n")

    # Load OCA file
    with open(oca_path, 'r') as f:
        oca = json.load(f)

    print(f"OCA: {oca.get('model', 'Unknown')} | {len(oca.get('channels', []))} channels | eqType={oca.get('eqType')}")

    # Detect mult eq type from OCA file
    oca_eq_type = oca.get('eqType', 0)
    mult_eq_type = ['MultEQ', 'XT', 'XT32'][oca_eq_type] if oca_eq_type in (0, 1, 2) else 'MultEQ'
    print(f"Detected MultEQ type from OCA: {mult_eq_type}\n")

    # Connect to AVR
    print(f"Connecting to {ip}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((ip, PORT))
    print("Connected\n")
    time.sleep(0.2)

    # GET_AVRINF - Get AVR info
    print("Sending GET_AVRINF...")
    sock.send(bytes.fromhex(GET_AVRINF_HEX))
    time.sleep(0.3)
    info = receive_json_response(sock)
    if info:
        eq_type_str = info.get('EQType', '')
        d_type = info.get('DType', 'float')
        coef_wait_time = info.get('CoefWaitTime', {})
        cv_ver = info.get('CVVer', 'Unknown')
        print(f"AVR: {eq_type_str} v{cv_ver}")
        print(f"DType: {d_type}")
        print(f"CoefWaitTime: {coef_wait_time}\n")

        # Update mult_eq_type based on actual AVR response
        detected_mult_eq_type = detect_mult_eq_type(eq_type_str)
        print(f"Detected MultEQ type from AVR: {detected_mult_eq_type}")
    else:
        print("Warning: No response to GET_AVRINF")
        d_type = 'float'
        coef_wait_time = {}
        detected_mult_eq_type = mult_eq_type

    # GET_AVRSTS - Get AVR status
    print("Sending GET_AVRSTS...")
    sock.send(bytes.fromhex(GET_AVRSTS_HEX))
    time.sleep(0.3)
    status = receive_json_response(sock)
    if not status:
        print("ERROR: No response to GET_AVRSTS")
        sock.close()
        return

    # Extract active channels and config
    raw_ch_setup = status.get('ChSetup', [])
    active_channels = [
        list(entry.keys())[0]
        for entry in raw_ch_setup
        if entry and list(entry.values())[0] != 'N'
    ]
    amp_assign = status.get('AmpAssign')
    assign_bin = status.get('AssignBin')

    print(f"Active channels: {', '.join(active_channels)}")
    print(f"AmpAssign: {amp_assign}")
    print(f"AssignBin: {assign_bin}\n")

    # Build channel info with byte mappings
    floor_channel_ids = {'FL', 'C', 'FR', 'SLA', 'SRA', 'SBL', 'SBR'}
    front_wide_channel_ids = {'FWL', 'FWR'}
    sub_channel_ids = {'SW1', 'SW2', 'SW3', 'SW4'}

    floor_channels = []
    other_channels = []
    front_wide_channels = []
    sub_channels = []

    for original_channel_id in active_channels:
        mapped_channel_id = map_channel_id_for_setdat(original_channel_id.upper())
        try:
            channel_byte = get_channel_type_byte(mapped_channel_id, detected_mult_eq_type)
            channel_info = {'id': original_channel_id, 'mappedId': mapped_channel_id, 'byte': channel_byte}

            if mapped_channel_id in floor_channel_ids:
                floor_channels.append(channel_info)
            elif mapped_channel_id in sub_channel_ids:
                sub_channels.append(channel_info)
            elif mapped_channel_id in front_wide_channel_ids:
                front_wide_channels.append(channel_info)
            else:
                other_channels.append(channel_info)
        except ValueError as e:
            print(f"Warning: Could not get channel byte for {original_channel_id}: {e}")

    # Sort by byte value
    def sort_by_byte(ch):
        return ch['byte']

    floor_channels.sort(key=sort_by_byte)
    other_channels.sort(key=sort_by_byte)
    front_wide_channels.sort(key=sort_by_byte)
    sub_channels.sort(key=sort_by_byte)

    channels_to_send_sorted = floor_channels + other_channels + front_wide_channels + sub_channels

    # ENTER_AUDY - Enter calibration mode
    print("Entering calibration mode (ENTER_AUDY)...")
    ack = send_and_wait_ack(sock, bytes.fromhex(ENTER_AUDY_HEX), timeout=10)
    if not ack:
        print("ERROR: Failed to enter calibration mode")
        sock.close()
        return
    print("Calibration mode entered\n")

    # SET_SETDAT - Send configuration
    print("Sending configuration (SET_SETDAT)...")
    try:
        send_set_dat_command(sock, status, raw_ch_setup, oca, channels_to_send_sorted, detected_mult_eq_type)
    except Exception as e:
        print(f"ERROR in SET_SETDAT: {e}")
        # Continue anyway per transfer.js error handling

    # INIT_COEFS for fixed data type
    if d_type.lower().startswith('fixed'):
        print("\nInitializing coefficients (INIT_COEFS)...")
        if coef_wait_time and 'Init' in coef_wait_time:
            wait_ms = coef_wait_time['Init'] * 3
            print(f"Waiting {wait_ms}ms...")
            time.sleep(wait_ms / 1000)

        ack = send_and_wait_ack(sock, bytes.fromhex(INIT_COEFS_HEX), timeout=10)
        if not ack:
            print("WARNING: No ACK for INIT_COEFS")

        if coef_wait_time and 'Init' in coef_wait_time:
            time.sleep(coef_wait_time['Init'] / 1000)

    # Determine converter function based on data type
    is_fixed = d_type.lower().startswith('fixed')

    def float_to_buffer_le(f: float) -> bytes:
        """Convert float to little-endian float32 bytes."""
        return struct.pack('<f', f)

    def fixed32_to_buffer_le(f: float) -> bytes:
        """Convert float to AVR fixed-point 32-bit representation."""
        int_val = java_float_to_fixed32bits(f)
        return struct.pack('<i', int_val)

    converter_func = fixed32_to_buffer_le if is_fixed else float_to_buffer_le

    # Process filter data for all channels
    print("\nProcessing filter data...")
    all_processed_data = {}

    for original_channel_id in active_channels:
        mapped_channel_id = map_channel_id_for_setdat(original_channel_id.upper())

        # Find channel data in OCA
        channel_filter_data = None
        for ch in oca.get('channels', []):
            if map_channel_id_for_setdat(ch.get('commandId', '').upper()) == mapped_channel_id:
                channel_filter_data = ch
                break

        if not channel_filter_data or not channel_filter_data.get('filter') or not channel_filter_data.get('filterLV'):
            print(f"Skipping {original_channel_id}: Missing data in OCA")
            continue

        try:
            processed_filter, processed_filter_lv = process_filter_data_for_transfer(
                channel_filter_data, detected_mult_eq_type, mapped_channel_id
            )
            all_processed_data[original_channel_id] = {
                'filter': processed_filter,
                'filterLV': processed_filter_lv
            }
        except Exception as e:
            print(f"Error processing {mapped_channel_id}: {e}")

    # Target curves: '00' = Flat, '01' = Reference
    target_curves = ['00', '01']
    # Sample rates: '00', '01', '02' for XT32
    sample_rates = ['00', '01', '02']

    # Send coefficient packets
    print("\nSending coefficient packets...")

    for tc in target_curves:
        curve_name = 'Reference' if tc == '01' else 'Flat'
        print(f"\nUploading {curve_name} mode filters =>")

        for channel_info in channels_to_send_sorted:
            original_channel_id = channel_info['id']
            mapped_channel_id = channel_info['mappedId']

            if original_channel_id not in all_processed_data:
                print(f"  --- Skipping Channel: {original_channel_id} (No pre-processed data) ---")
                continue

            print(f"  >> Channel: {original_channel_id}")

            processed_data = all_processed_data[original_channel_id]
            coeffs = processed_data['filter'] if tc == '01' else processed_data['filterLV']

            # Convert coefficients to buffers
            coeff_buffers = [converter_func(c) for c in coeffs]

            # Build packet config
            channel_config = build_packet_config(len(coeff_buffers))

            # Get channel byte
            channel_byte = get_channel_type_byte(mapped_channel_id, detected_mult_eq_type)

            # Send for all sample rates
            for sr in sample_rates:
                packets = generate_coef_packets(coeff_buffers, channel_config, tc, sr, channel_byte)

                for i, packet in enumerate(packets):
                    label = f"Coef Pkt {i + 1}/{len(packets)} ({original_channel_id} {curve_name} SR{sr})"
                    ack = send_and_wait_ack(sock, packet, timeout=10)
                    if not ack:
                        print(f"    WARNING: No ACK for {label}")

                time.sleep(0.02)

        time.sleep(0.1)

    # FINZ_COEFS - Finalize coefficients
    print("\nFinalizing coefficients (FINZ_COEFS)...")
    ack = send_and_wait_ack(sock, bytes.fromhex(FINZ_COEFS_HEX), timeout=15)
    if not ack:
        print("WARNING: No ACK for FINZ_COEFS")
    time.sleep(0.02)

    # SET_AUDYFINFLG = "Fin" - Final flag
    print("Setting final flag (AudyFinFlg=Fin)...")
    final_flag_payload = {"AudyFinFlg": "Fin"}
    final_flag_json = json.dumps(final_flag_payload)
    final_flag_packet = build_avr_packet('SET_SETDAT', final_flag_json, 0, 0)
    ack = send_and_wait_ack(sock, final_flag_packet, timeout=10)
    if not ack:
        print("WARNING: No ACK for AudyFinFlg=Fin")
    time.sleep(0.02)

    # EXIT_AUDMD - Exit calibration mode
    print("Exiting calibration mode (EXIT_AUDMD)...")
    ack = send_and_wait_ack(sock, bytes.fromhex(EXIT_AUDMD_HEX), timeout=10)
    if not ack:
        print("WARNING: No ACK for EXIT_AUDMD")

    # Close connection
    sock.close()
    print("\nDisconnected")
    print("\n" + "=" * 50)
    print(f"TRANSFER COMPLETE (preset {preset}) -- power cycle AVR to apply")
    print("=" * 50)


def is_naN(val) -> bool:
    """Check if value is NaN."""
    try:
        return math.isnan(val)
    except:
        return False


# ─── Entry Point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Transfer OCA calibration to AVR')
    parser.add_argument('--switch-preset', '--switch', metavar='PRESET',
                        choices=['1', '2'], help='Just switch preset without transfer')
    parser.add_argument('oca_file', nargs='?', help='Path to .oca calibration file')
    parser.add_argument('avr_ip', nargs='?', default='192.168.50.2', help='AVR IP address')
    parser.add_argument('--preset', '--slot', '-s', choices=['1', '2'], default='1',
                        help='Target preset: 1 or 2 (default: 1)')
    args = parser.parse_args()

    ip = args.avr_ip

    if args.switch_preset:
        switch_preset(ip, args.switch_preset)
        return

    if not args.oca_file:
        parser.print_help()
        return

    oca_path = Path(args.oca_file)
    if not oca_path.exists():
        print(f"ERROR: OCA file not found: {oca_path}")
        sys.exit(1)

    try:
        transfer(oca_path, ip, args.preset)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
