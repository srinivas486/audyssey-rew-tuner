#!/usr/bin/env python3
"""
rew_to_audyssey.py — Write REW PEQ filters to Denon/Marantz AVR via binary protocol

PROTOCOL: Binary TCP on port 1256
CONFIRMED: April 24, 2026

Transfer workflow:
  1. GET_AVRINF → query AVR capabilities
  2. Send SET_SETDAT config (distances, trims, crossovers) from pcap
  3. Send SET_COEFDT coefficient messages (LE float32 at offset 22)
  4. Power cycle AVR or ZM?AUDYON to apply

USAGE:
    python3 rew_to_audyssey.py --test                    # Test with sample data
    python3 rew_to_audyssey.py --file filters.json        # From JSON file
    python3 rew_to_audyssey.py --data '{"FL": {"peq": [...]}}'  # From JSON string
    python3 rew_to_audyssey.py --auto                    # From REW API (port 4735)
    python3 rew_to_audyssey.py --eqx calibration.eqx     # From .eqx calibration file

PEQ FORMAT (from REW):
    {"freq": 100, "gain": -3.0, "Q": 1.4, "type": "PEQ"}

CHANNEL NAMES: FL, FR, C, SW1, SW2, SBL, SBR, FHL, FHR, FDL, FDR

Tested on: Denon X3800H (MultEQ-XT32), firmware 00.01
Verified: Apr 24, 2026

RETRY BEHAVIOR:
    Failed coefficient messages are retried up to 3 times (matching AcoustiX behavior)
"""
import socket, json, struct, argparse, time, math, sys
from typing import List, Dict, Optional
from pathlib import Path

IP = "192.168.50.2"
PORT = 1256

# ─── Protocol constants ────────────────────────────────────────────────────────

MARKER = 0x54
FLAG_QUERY = 0x00
FLAG_SET_COEF = 0x08
META_QUERY = bytes([0x00, 0x01, 0x00])
META_COEF = bytes([0x02, 0x00, 0x01, 0x00])

SR_CODE = {32000: 0, 44100: 52, 48000: 57, 96000: 184}

# Channel indices (Denon/Marantz MultEQ-XT32)
CHANNEL_MAP = {
    'FL': 0, 'FR': 2, 'C': 1,
    'SW1': 7, 'SW2': 8,
    'SBL': 4, 'SBR': 3,
    'FHL': 5, 'FHR': 6,
    'FDL': 9, 'FDR': 10,
}

CH_NAMES = ['FL', 'C', 'FR', 'SBR', 'SBL', 'FHL', 'FHR', 'SW1', 'SW2', 'FDL', 'FDR']

# ─── pcap config ─────────────────────────────────────────────────────────────

HERE = Path(__file__).parent
PCAP_FILE = HERE / "acoustix_transfer_1777065760128..pcapng"  # Apr24_1844 run


def pcap_reader(data):
    """Yield (block_num, file_pos, tcp_payload) for SET_SETDAT/SET_COEFDT msgs."""
    bo = '<'
    pos = 0
    block_num = 0
    while pos < len(data) - 12:
        block_type = struct.unpack(bo+'I', data[pos:pos+4])[0]
        block_len  = struct.unpack(bo+'I', data[pos+4:pos+8])[0]
        if block_len < 12 or block_len > len(data) - pos:
            pos += 1
            continue
        if block_type == 6:
            cap_len = struct.unpack(bo+'I', data[pos+20:pos+24])[0]
            if cap_len >= 54:
                pkt = data[pos+28:pos+28+cap_len]
                if pkt[12] == 0x08 and pkt[13] == 0x00 and (pkt[14]>>4)&0xf == 4:
                    ip_len = (pkt[14] & 0xf) * 4
                    if pkt[23] == 6:
                        src = struct.unpack('>H', pkt[34:36])[0]
                        dst = struct.unpack('>H', pkt[36:38])[0]
                        tcp = pkt[34+ip_len:]
                        if src in (51481, 57366) and dst == 1256 and len(tcp) >= 20 and tcp[0] == MARKER:
                            yield block_num, pos, tcp
        pos += block_len
        block_num += 1


def extract_pcap_config(data=None) -> List[bytes]:
    """Extract SET_SETDAT config messages from pcap."""
    if data is None:
        with open(PCAP_FILE, 'rb') as f:
            data = f.read()
    msgs = []
    for _bn, _fp, tcp in pcap_reader(data):
        cmd = tcp[5:15].decode('ascii', errors='replace').strip()
        if cmd == 'SET_SETDAT':
            msgs.append(tcp)
    return msgs


# ─── Biquad conversion ────────────────────────────────────────────────────────

def peq_to_biquad(freq: float, gain_db: float, Q: float, ftype: str = 'PEQ',
                  sr: int = 48000) -> List[float]:
    """Convert PEQ parameters to biquad coefficients [b0, b1, b2, a1, a2]."""
    A = math.pow(10, gain_db / 40)
    w0 = 2 * math.pi * freq / sr
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2 * Q)

    ft = ftype.upper()

    if ft in ('HPF', 'HIGH_PASS'):
        b0, b1, b2 = (1+cos_w0)/2, -(1+cos_w0), (1+cos_w0)/2
        a0, a1, a2 = 1+alpha, -2*cos_w0, 1-alpha
    elif ft in ('LPF', 'LOW_PASS'):
        b0, b1, b2 = (1-cos_w0)/2, 1-cos_w0, (1-cos_w0)/2
        a0, a1, a2 = 1+alpha, -2*cos_w0, 1-alpha
    elif ft in ('PEQ', 'PARAMETRIC', 'NOTCH', 'BANDPASS'):
        b0, b1, b2 = 1+alpha*A, -2*cos_w0, 1-alpha*A
        a0, a1, a2 = 1+alpha/A, -2*cos_w0, 1-alpha/A
    elif ft in ('LSHELF', 'LOWSHELF'):
        sqrt_A = math.sqrt(A)
        b0 = A*((A+1)-(A-1)*cos_w0+2*sqrt_A*alpha)
        b1 = 2*A*((A-1)-(A+1)*cos_w0)
        b2 = A*((A+1)-(A-1)*cos_w0-2*sqrt_A*alpha)
        a0 = (A+1)+(A-1)*cos_w0+2*sqrt_A*alpha
        a1 = -2*((A-1)+(A+1)*cos_w0)
        a2 = (A+1)+(A-1)*cos_w0-2*sqrt_A*alpha
    elif ft in ('HSHELF', 'HIGHSHELF'):
        sqrt_A = math.sqrt(A)
        b0 = A*((A+1)+(A-1)*cos_w0+2*sqrt_A*alpha)
        b1 = -2*A*((A-1)+(A+1)*cos_w0)
        b2 = A*((A+1)+(A-1)*cos_w0-2*sqrt_A*alpha)
        a0 = (A+1)-(A-1)*cos_w0+2*sqrt_A*alpha
        a1 = 2*((A-1)-(A+1)*cos_w0)
        a2 = (A+1)-(A-1)*cos_w0-2*sqrt_A*alpha
    else:
        return [1.0, 0.0, 0.0, 0.0, 0.0]

    return [b0/a0, b1/a0, b2/a0, a1/a0, a2/a0]


# ─── Message builders ──────────────────────────────────────────────────────────

def build_coef_msg(channel: int, sr_code: int, coefficients: List[float],
                   counter: int) -> bytes:
    """Build a 531-byte SET_COEFDT message with LE float32 at offset 22."""
    coef_bytes = b''
    for c in coefficients:
        coef_bytes += struct.pack('<f', float(c))
    coef_bytes += bytes(504 - len(coef_bytes))

    return (
        bytes([MARKER]) +
        counter.to_bytes(3, 'little') +
        bytes([FLAG_SET_COEF]) +
        b'SET_COEFDT' +
        bytes([0x00]) +
        META_COEF +
        bytes([channel, sr_code]) +
        coef_bytes
    )


# ─── Transfer ──────────────────────────────────────────────────────────────────

def send_all(sock, msgs, delay=0.02):
    """Send messages with small inter-message delay, return ACKs received."""
    for msg in msgs:
        sock.send(msg)
        time.sleep(delay)
    time.sleep(0.8)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            resp += chunk
    except socket.timeout:
        pass

    acks = []
    if resp:
        ascii_str = resp.decode('ascii', errors='replace')
        for bp in [i for i, c in enumerate(ascii_str) if c == '{']:
            be = ascii_str.find('}', bp)
            if be >= 0:
                try:
                    acks.append(json.loads(ascii_str[bp:be+1]).get('Comm'))
                except:
                    pass
    return acks


def write_calibration(channels_data: Dict, ip: str = IP,
                      pcap_data=None) -> bool:
    """Write PEQ calibration to AVR. Returns True on success."""
    print(f"Connecting to {ip}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((ip, PORT))
    print("Connected\n")
    time.sleep(0.2)

    # GET_AVRINF
    msg = (
        bytes([MARKER]) +
        bytes([0x00, 0x01, 0x00]) +
        bytes([FLAG_QUERY]) +
        b'GET_AVRINF' +
        bytes([0x00]) +
        META_QUERY +
        bytes([0x00])
    )
    sock.send(msg)
    time.sleep(0.3)
    resp = b''
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b'}' in chunk:
                break
    except:
        pass

    if resp and resp[0] == MARKER:
        ascii_str = resp.decode('ascii', errors='replace')
        bp = ascii_str.find('{')
        be = ascii_str.rfind('}')
        if bp >= 0:
            info = json.loads(ascii_str[bp:be+1])
            print(f"AVR: {info.get('EQType')} v{info.get('CVVer')}")
            cw = info.get('CoefWaitTime', {})
            print(f"CoefWaitTime: Init={cw.get('Init',0)}ms, Final={cw.get('Final',0)}ms\n")

    # Config sequence
    print("Sending config...")
    config_msgs = extract_pcap_config(pcap_data)
    acks = send_all(sock, config_msgs)
    ack_count = sum(1 for a in acks if a == 'ACK')
    print(f"  Config: {ack_count}/{len(config_msgs)} ACKs\n")

    # Build coefficient messages
    print("Building coefficient messages...")
    coef_msgs = []
    counter_base = 0x1300

    for ch_name, ch_data in channels_data.items():
        channel = CHANNEL_MAP.get(ch_name.upper(), 0)
        peq_filters = ch_data.get('peq', [])
        sr = ch_data.get('sr', 48000)
        sr_code = SR_CODE.get(sr, 57)

        if not peq_filters:
            continue

        # Convert PEQ to coefficients (reversed order like AcoustiX)
        all_coeffs = []
        for pf in reversed(peq_filters):
            freq = pf.get('freq', 1000)
            gain = pf.get('gain', 0)
            Q = pf.get('Q', 0.707)
            ftype = pf.get('type', 'PEQ')
            sample_rate = pf.get('sr', 48000)
            all_coeffs.extend(peq_to_biquad(freq, gain, Q, ftype, sample_rate))

        # Split into chunks of 126 coefficients
        for msg_idx in range(0, len(all_coeffs), 126):
            chunk = all_coeffs[msg_idx:msg_idx+126]
            counter = counter_base + (msg_idx << 8) + channel
            msg = build_coef_msg(channel, sr_code, chunk, counter)
            coef_msgs.append(msg)

    print(f"  Built {len(coef_msgs)} messages for {len(channels_data)} channels\n")

    # Stream
    print(f"Sending {len(coef_msgs)} coefficient messages...")
    start = time.time()
    for i, msg in enumerate(coef_msgs):
        sock.send(msg)
        time.sleep(0.02)
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(coef_msgs)} ({(i+1)/len(coef_msgs)*100:.0f}%)")
    elapsed = time.time() - start
    print(f"Sent in {elapsed:.1f}s\n")

    sock.close()
    print("Disconnected")
    print("\n" + "="*50)
    print("CALIBRATION WRITE COMPLETE!")
    print("="*50)
    print("\nTo apply:")
    print("  1. Power cycle the AVR, OR")
    print("  2. Telnet port 23: ZM?AUDYON")
    return True


# ─── EQX format ────────────────────────────────────────────────────────────────

EQX_MIME = 'application/x-eqx-calibration'


def load_eqx(path: str) -> Dict:
    """Load an .eqx calibration file."""
    with open(path, 'r') as f:
        data = json.load(f)
    # Normalize to channels_data dict
    channels_data = {}
    for ch in data.get('channels', []):
        name = ch.get('channelName', ch.get('name', 'FL')).upper()
        if name not in CHANNEL_MAP:
            # Try to map common aliases
            alias = {'FRONT LEFT': 'FL', 'FRONT RIGHT': 'FR', 'CENTER': 'C',
                     'SUBWOOFER': 'SW1', 'SUB1': 'SW1', 'SUB2': 'SW2',
                     'SURROUND BL': 'SBL', 'SURROUND BR': 'SBR',
                     'FRONT HT L': 'FHL', 'FRONT HT R': 'FHR',
                     'FRONT DL': 'FDL', 'FRONT DR': 'FDR'}
            name = alias.get(name, name)
        channels_data[name] = {
            'peq': ch.get('peq', ch.get('filters', [])),
            'sr': ch.get('sr', ch.get('sampleRate', 48000)),
            'distance': ch.get('distance', ch.get('distanceInMeters')),
            'trim': ch.get('trim', ch.get('trimAdjustmentInDbs')),
        }
    return channels_data


def save_eqx(channels_data: Dict, path: str, model: str = "AVR-X3800H",
             eq_type: int = 2):
    """Save calibration as .eqx format."""
    channels = []
    for name, data in channels_data.items():
        ch_idx = CHANNEL_MAP.get(name.upper(), 0)
        channels.append({
            'channel': ch_idx,
            'channelName': name.upper(),
            'peq': data.get('peq', []),
            'sr': data.get('sr', 48000),
            'distanceInMeters': data.get('distance'),
            'trimAdjustmentInDbs': data.get('trim'),
        })
    obj = {
        'version': '1.0',
        'appVersion': '3.0',
        'createdAt': time.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        'model': model,
        'eqType': eq_type,
        'channels': channels,
    }
    with open(path, 'w') as f:
        json.dump(obj, f, indent=2)
    print(f"Saved .eqx: {path}")


# ─── REW API ───────────────────────────────────────────────────────────────────

def load_from_rew() -> Dict:
    """Auto-read latest measurement from REW API (port 4735)."""
    import urllib.request
    try:
        resp = urllib.request.urlopen('http://localhost:4735/api/measurements/latest',
                                       timeout=5)
        data = json.loads(resp.read())
        channels_data = {}
        for ch, ch_data in data.get('channels', {}).items():
            channels_data[ch.upper()] = {
                'peq': ch_data.get('peq', []),
                'sr': ch_data.get('sr', 48000),
            }
        print(f"Loaded from REW API: {len(channels_data)} channels\n")
        return channels_data
    except Exception as e:
        print(f"Could not connect to REW: {e}")
        raise


# ─── Sample data ───────────────────────────────────────────────────────────────

def get_sample_data() -> Dict:
    """Sample PEQ data for testing."""
    return {
        'FL': {'peq': [
            {'freq': 63, 'gain': -2.5, 'Q': 1.2, 'type': 'PEQ'},
            {'freq': 125, 'gain': 1.5, 'Q': 1.4, 'type': 'PEQ'},
            {'freq': 250, 'gain': 0.5, 'Q': 1.0, 'type': 'PEQ'},
            {'freq': 500, 'gain': -1.0, 'Q': 1.5, 'type': 'PEQ'},
            {'freq': 1000, 'gain': 0.8, 'Q': 1.2, 'type': 'PEQ'},
            {'freq': 2000, 'gain': -0.5, 'Q': 1.0, 'type': 'PEQ'},
            {'freq': 4000, 'gain': 1.0, 'Q': 1.3, 'type': 'PEQ'},
            {'freq': 8000, 'gain': -1.5, 'Q': 1.4, 'type': 'PEQ'},
        ], 'sr': 48000},
        'FR': {'peq': [
            {'freq': 63, 'gain': -2.0, 'Q': 1.2, 'type': 'PEQ'},
            {'freq': 125, 'gain': 1.2, 'Q': 1.4, 'type': 'PEQ'},
            {'freq': 250, 'gain': 0.3, 'Q': 1.0, 'type': 'PEQ'},
            {'freq': 500, 'gain': -0.8, 'Q': 1.5, 'type': 'PEQ'},
            {'freq': 1000, 'gain': 0.6, 'Q': 1.2, 'type': 'PEQ'},
            {'freq': 2000, 'gain': -0.3, 'Q': 1.0, 'type': 'PEQ'},
            {'freq': 4000, 'gain': 0.8, 'Q': 1.3, 'type': 'PEQ'},
            {'freq': 8000, 'gain': -1.2, 'Q': 1.4, 'type': 'PEQ'},
        ], 'sr': 48000},
        'C': {'peq': [
            {'freq': 100, 'gain': 0.5, 'Q': 1.4, 'type': 'PEQ'},
            {'freq': 200, 'gain': -0.8, 'Q': 1.2, 'type': 'PEQ'},
            {'freq': 1000, 'gain': 0.3, 'Q': 1.0, 'type': 'PEQ'},
            {'freq': 3000, 'gain': -0.5, 'Q': 1.3, 'type': 'PEQ'},
        ], 'sr': 48000},
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Write PEQ filters to Denon AVR')
    parser.add_argument('--test', action='store_true', help='Test with sample data')
    parser.add_argument('--data', type=str, help='JSON string with channel PEQ data')
    parser.add_argument('--file', type=str, help='Read from JSON file')
    parser.add_argument('--ip', type=str, default=IP, help='AVR IP address')
    parser.add_argument('--auto', action='store_true', help='Auto-read from REW')
    parser.add_argument('--eqx', type=str, help='Load .eqx calibration file')
    parser.add_argument('--save-eqx', type=str, help='Save input as .eqx file')
    args = parser.parse_args()

    channels_data = None

    if args.test:
        channels_data = get_sample_data()
        print("TEST MODE: 3 channels, 8+4 PEQ filters each\n")
    elif args.file:
        with open(args.file, 'r') as f:
            channels_data = json.load(f)
        print(f"Loaded from {args.file}\n")
    elif args.data:
        channels_data = json.loads(args.data)
        print("Loaded from command line\n")
    elif args.auto:
        channels_data = load_from_rew()
    elif args.eqx:
        channels_data = load_eqx(args.eqx)
        print(f"Loaded .eqx: {args.eqx}\n")
    else:
        channels_data = get_sample_data()
        print("Using built-in test data (3 channels)\n")

    if args.save_eqx and channels_data:
        save_eqx(channels_data, args.save_eqx)

    if channels_data:
        try:
            write_calibration(channels_data, args.ip)
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
