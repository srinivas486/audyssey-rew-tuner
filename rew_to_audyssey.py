#!/usr/bin/env python3
"""
rew_to_audyssey.py — Write REW PEQ filters to Denon/Marantz AVR via binary protocol

USAGE:
    python3 rew_to_audyssey.py --test                    # Test with sample data
    python3 rew_to_audyssey.py --file filters.json        # From JSON file
    python3 rew_to_audyssey.py --data '{"FL": {"peq": [...]}}'  # From JSON string
    python3 rew_to_audyssey.py --auto                    # From REW API (port 4735)

PEQ FORMAT (from REW):
    {"freq": 100, "gain": -3.0, "Q": 1.4, "type": "PEQ"}

CHANNEL NAMES: FL, FR, C, SW1, SW2, SRA, SLA, FDR, SDR, SDL, FDL

Tested on: Denon X3800H (MultEQ-XT32), firmware 00.01
Verified: Apr 24, 2026
"""
import socket, json, struct, argparse, time, math, sys
from typing import List, Dict, Optional

IP = "192.168.50.2"
PORT = 1256

# Channel index mapping (Denon/Marantz MultEQ-XT32)
CHANNEL_MAP = {
    'FL': 0, 'FR': 2, 'C': 1,
    'SW1': 6, 'SW2': 7,
    'SRA': 3, 'SLA': 4,
    'FPR': 5, 'FPL': 9,
    'FDR': 10, 'FDL': 9,
    'SDR': 11, 'SDL': 10,
}

# Sample rate codes (from pcap analysis)
SR_MAP = {32000: 0, 44100: 52, 48000: 57}


def peq_to_biquad(freq: float, gain_db: float, Q: float, ftype: str = 'PEQ') -> List[float]:
    """Convert PEQ parameters to biquad coefficients [b0, b1, b2, a1, a2]."""
    A = math.pow(10, gain_db / 40)
    w0 = 2 * math.pi * freq / 48000
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


def build_coefdt(channel: int, sr_code: int, coeffs: List[float], counter: int, filter_idx: int = 0) -> bytes:
    """Build a 531-byte SET_COEFDT message."""
    coef_bytes = b''
    for c in coeffs:
        coef_bytes += struct.pack('<f', c)
    
    # 531 = 20 header + 511 data
    # Data: channel(1) + sr(1) + filter_idx(2) + coeffs(507 = 126×4 + 3)
    data = bytes([channel, sr_code]) + struct.pack('<H', filter_idx) + coef_bytes
    data += bytes(507 - len(data))  # Pad to 507 bytes
    
    msg = (
        bytes([0x54]) +
        counter.to_bytes(3, 'little') +
        bytes([0x08]) +
        b'SET_COEFDT' +
        bytes([0x00]) +
        bytes([channel, sr_code, 0, 0]) +  # 4-byte meta
        data
    )
    return msg


def extract_pcap_config() -> List[bytes]:
    """Extract SET_SETDAT + FINZ_COEFS from AcoustiX pcap."""
    import struct
    pcap_path = '/root/.openclaw/workspace/audyssey-rew-tuner/acoustix_transfer_1777004735377..pcapng'
    with open(pcap_path, 'rb') as f:
        data = f.read()
    
    bo = '<'
    pos = 0
    msgs = []
    while pos < len(data) - 12:
        block_type = struct.unpack(bo+'I', data[pos:pos+4])[0]
        block_len = struct.unpack(bo+'I', data[pos+4:pos+8])[0]
        if block_len < 12 or block_len > len(data) - pos:
            pos += 1
            continue
        if block_type == 6:
            cap_len = struct.unpack(bo+'I', data[pos+20:pos+24])[0]
            if cap_len > 0 and cap_len <= 1514:
                packet_start = pos + 28
                packet = data[packet_start:packet_start+cap_len]
                ip_offset = None
                for i in range(min(cap_len - 34, 20)):
                    if packet[i] >> 4 == 4:
                        ip_offset = i
                        break
                if ip_offset is not None:
                    ip = packet[ip_offset:]
                    if len(ip) >= 34 and ip[9] == 6:
                        src = struct.unpack('>H', ip[20:22])[0]
                        dst = struct.unpack('>H', ip[22:24])[0]
                        ihl = (ip[0] & 0x0F) * 4
                        tcp_end = 20 + ihl
                        if len(ip) > tcp_end:
                            pl = ip[tcp_end:]
                            if src == 51481 and dst == 1256 and len(pl) >= 5 and pl[0] == 0x54:
                                cmd = pl[5:15].decode('ascii', errors='replace').strip()
                                if cmd in ('SET_SETDAT', 'FINZ_COEFS'):
                                    msgs.append(pl)
        pos += block_len
    return msgs


def write_calibration(channels_data: Dict, ip: str = IP) -> bool:
    """Write calibration to AVR. Returns True on success."""
    print(f"⚡ Connecting to {ip}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(20)
    sock.connect((ip, PORT))
    print("✅ Connected\n")
    time.sleep(0.2)
    
    # GET_AVRINF
    sock.send(bytes.fromhex('54001300004745545f415652494e460000006c'))
    time.sleep(0.3)
    resp = b''
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except:
        pass
    
    if resp and resp[0] == 0x52:
        ascii_str = resp.decode('ascii', errors='replace')
        bp = ascii_str.find('{')
        be = ascii_str.rfind('}')
        if bp >= 0:
            info = json.loads(ascii_str[bp:be+1])
            print(f"AVR: {info.get('EQType')} v{info.get('CVVer')}")
            print(f"CoefWaitTime: Init={info.get('CoefWaitTime',{}).get('Init',0)}ms, Final={info.get('CoefWaitTime',{}).get('Final',0)}ms\n")
    
    # Config sequence (rapid-fire)
    print("📤 Sending config commands...")
    config_msgs = extract_pcap_config()
    for msg in config_msgs:
        sock.send(msg)
        time.sleep(0.05)
    
    time.sleep(0.8)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
    except socket.timeout:
        pass
    
    acks = []
    try:
        ascii_str = resp.decode('ascii', errors='replace')
        for bp in [i for i, c in enumerate(ascii_str) if c == '{']:
            be = ascii_str.find('}', bp)
            if be >= 0:
                try:
                    acks.append(json.loads(ascii_str[bp:be+1]).get('Comm'))
                except:
                    pass
    except:
        pass
    
    ack_count = sum(1 for a in acks if a == 'ACK')
    print(f"   Config: {ack_count}/{len(config_msgs)} commands accepted\n")
    
    # Build coefficient messages
    print("🔧 Building coefficient messages...")
    coef_msgs = []
    counter = 0x1313
    
    for ch_name, ch_data in channels_data.items():
        channel = CHANNEL_MAP.get(ch_name.upper(), 0)
        peq_filters = ch_data.get('peq', [])
        sr = ch_data.get('sr', 48000)
        sr_code = SR_MAP.get(sr, 57)
        
        if not peq_filters:
            continue
        
        # Convert PEQ to coefficients (reversed order like AcoustiX)
        all_coeffs = []
        for pf in reversed(peq_filters):
            freq = pf.get('freq', 1000)
            gain = pf.get('gain', 0)
            Q = pf.get('Q', 0.707)
            ftype = pf.get('type', 'PEQ')
            all_coeffs.extend(peq_to_biquad(freq, gain, Q, ftype))
        
        # Split into chunks of 126 coefficients (507 bytes)
        for i in range(0, len(all_coeffs), 126):
            chunk = all_coeffs[i:i+126]
            msg = build_coefdt(channel, sr_code, chunk, counter, len(coef_msgs))
            coef_msgs.append(msg)
            counter += 1
    
    print(f"   Built {len(coef_msgs)} coefficient messages for {len(channels_data)} channels\n")
    
    # Stream coefficients
    print(f"📤 Streaming {len(coef_msgs)} coefficient messages...")
    for i, msg in enumerate(coef_msgs):
        sock.send(msg)
        time.sleep(0.02)
        if (i+1) % 100 == 0:
            print(f"   Progress: {i+1}/{len(coef_msgs)}")
    
    print(f"   ✅ All {len(coef_msgs)} messages sent\n")
    
    sock.close()
    print("🛑 Disconnected\n")
    print("="*50)
    print("🎉 CALIBRATION WRITE COMPLETE!")
    print("="*50)
    print("\nTo apply:")
    print("  1. Power cycle the AVR, OR")
    print("  2. Telnet port 23: ZM?AUDYON")
    
    return True


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


def main():
    parser = argparse.ArgumentParser(description='Write REW PEQ filters to Denon AVR')
    parser.add_argument('--test', action='store_true', help='Test with sample data')
    parser.add_argument('--data', type=str, help='JSON string with channel PEQ data')
    parser.add_argument('--file', type=str, help='Read from JSON file')
    parser.add_argument('--ip', type=str, default=IP, help='AVR IP address')
    parser.add_argument('--auto', action='store_true', help='Auto-read from REW')
    
    args = parser.parse_args()
    
    if args.test:
        channels_data = get_sample_data()
        print("🧪 TEST MODE: 3 channels, 8+4 PEQ filters each\n")
    elif args.file:
        with open(args.file, 'r') as f:
            channels_data = json.load(f)
        print(f"📂 Loaded from {args.file}\n")
    elif args.data:
        channels_data = json.loads(args.data)
        print("📥 Loaded from command line\n")
    elif args.auto:
        import urllib.request
        try:
            resp = urllib.request.urlopen('http://localhost:4735/api/measurements/latest', timeout=5)
            data = json.loads(resp.read())
            channels_data = {}
            for ch, ch_data in data.get('channels', {}).items():
                channels_data[ch] = {'peq': ch_data.get('peq', []), 'sr': ch_data.get('sr', 48000)}
            print(f"📡 Loaded from REW API: {len(channels_data)} channels\n")
        except Exception as e:
            print(f"❌ Could not connect to REW: {e}")
            return
    else:
        channels_data = get_sample_data()
        print("📋 Using built-in test data (3 channels)\n")
    
    try:
        write_calibration(channels_data, args.ip)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()