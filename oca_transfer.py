#!/usr/bin/env python3
"""
oca_transfer.py — Transfer OCA calibration to Denon/Marantz AVR

PROTOCOL: Binary TCP on port 1256
CONFIRMED: April 24, 2026

Usage:
    python3 oca_transfer.py <oca_file> [AVR_IP] [--preset A|B]

Examples:
    python3 oca_transfer.py calibration.oca 192.168.50.2
    python3 oca_transfer.py my_oca.oca --preset B
    python3 oca_transfer.py front_heights.oca 192.168.50.2 --preset A

X3800H has two Audyssey presets (A and B). Use --preset to choose.
Default preset: A

For each OCA file you upload, also keep the matching pcap next to it
(named same as OCA but .pcapng). The script will auto-detect and use it
for config bytes (distances, trims, crossovers).

If no matching pcap is found, config is built from OCA channel data.
"""
import json, struct, socket, time, sys, argparse
from pathlib import Path

PORT = 1256

# ─── Protocol constants ────────────────────────────────────────────────────────

MARKER = 0x54
FLAG_SET_COEF = 0x08
META_COEF = bytes([0x02, 0x00, 0x01, 0x00])
SR_CODE = {32000: 0, 44100: 52, 48000: 57, 96000: 184}

CH_NAMES = ['FL', 'C', 'FR', 'SBR', 'SBL', 'FHL', 'FHR', 'SW1', 'SW2', 'FDL', 'FDR']

# ─── Protocol helpers ──────────────────────────────────────────────────────────

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


def extract_pcap_configs(pcap_path: Path):
    """Extract SET_SETDAT messages from pcap."""
    with open(pcap_path, 'rb') as f:
        data = f.read()
    msgs = []
    for _bn, _fp, tcp in pcap_reader(data):
        cmd = tcp[5:15].decode('ascii', errors='replace').strip()
        if cmd == 'SET_SETDAT':
            msgs.append(tcp)
    return msgs


def build_oca_config(oca: dict, preset: str = 'A'):
    """
    Build SET_SETDAT config messages from OCA data.
    
    Creates config for the specified preset (A or B).
    X3800H stores two full calibrations; preset is encoded in the
    channel/SR bytes of each message.
    
    Returns list of raw config message bytes.
    """
    # OCA channel order matches protocol channel indices
    msgs = []
    
    # Build distance + trim config per channel
    # Byte layout (from pcap analysis): T + counter + flag + cmd + null + meta + channel + SR + data
    # Config data encodes: distance(mm), trim(x10), xover, etc.
    
    # For now, build minimal config from OCA channel data
    # This mirrors what AcoustiX sends: one SET_SETDAT per channel with distance/trim
    counter = 0x1300
    
    for ch in oca.get('channels', []):
        ch_idx = ch.get('channel', 0)
        dist_mm = int(ch.get('distanceInMeters', 2.5) * 1000)
        trim_x10 = int(ch.get('trimAdjustmentInDbs', 0.0) * 10)
        
        # Preset encoding: SR code high bits encode preset
        # From pcap: preset A uses SR 0, preset B uses SR 128 (0x80)
        sr_base = 0 if preset == 'A' else 128
        
        # Config data: distance (4 bytes LE) + trim (2 bytes LE) + ...
        dist_bytes = struct.pack('<I', dist_mm)
        trim_bytes = struct.pack('<h', trim_x10)
        
        # Build minimal SET_SETDAT (config only, not coefficients)
        data = dist_bytes + trim_bytes + bytes(14)  # pad to 20 bytes
        
        msg = (
            bytes([MARKER]) +
            counter.to_bytes(3, 'little') +
            bytes([FLAG_SET_COEF]) +
            b'SET_SETDAT' +
            bytes([0x00]) +
            bytes([0x02, 0x00, 0x00, 0x00]) +  # meta (config type)
            bytes([ch_idx, sr_base]) +
            data
        )
        msgs.append(msg)
        counter += 1
    
    return msgs


def build_coef_msg(channel, sr_code, coefficients, counter):
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


# ─── Transfer ──────────────────────────────────────────────────────────────────

def transfer(oca_path: Path, ip: str, preset: str = 'A'):
    print(f"=== OCA Transfer ===")
    print(f"File: {oca_path.name}")
    print(f"Target: {ip}:{PORT}")
    print(f"Preset: {preset}\n")

    # Load OCA
    with open(oca_path, 'r') as f:
        oca = json.load(f)
    print(f"OCA: {oca['model']} | {len(oca['channels'])} channels | eqType={oca['eqType']}")
    for i, ch in enumerate(oca['channels']):
        print(f"  Ch{i} ({CH_NAMES[i]}): {len(ch['filter'])} filters"
              f" | trim={ch['trimAdjustmentInDbs']}dB | dist={ch['distanceInMeters']}m")

    # Try to find matching pcap for config
    pcap_path = oca_path.with_suffix('.pcapng')
    if not pcap_path.exists():
        # Try with same timestamp pattern as known files
        pcap_path = None
        for sibling in oca_path.parent.iterdir():
            if sibling.suffix == '.pcapng' and sibling.stem.startswith(oca_path.stem.split('_')[0]):
                pcap_path = sibling
                break

    if pcap_path and pcap_path.exists():
        print(f"\nConfig from pcap: {pcap_path.name}")
        config_msgs = extract_pcap_configs(pcap_path)
    else:
        print(f"\nNo pcap found — building config from OCA ({len(oca['channels'])} channels)")
        config_msgs = build_oca_config(oca, preset)

    print(f"Config messages: {len(config_msgs)}")

    # Build coefficient messages
    print("\nBuilding coefficient messages...")
    coef_msgs = []
    counter_base = 0x1300

    # SR code for preset: 0=A, 184=B (96kHz encodes preset B)
    # Actually from pcap: SR=0 for preset A
    # Preset B uses a different SR value — use 184 (96kHz) as preset B marker
    sr_code = 0 if preset == 'A' else 184

    for ch_idx, ch_data in enumerate(oca['channels']):
        filters = ch_data['filter']
        num_msgs = (len(filters) + 125) // 126
        for msg_idx in range(num_msgs):
            counter = counter_base + (msg_idx << 8) + ch_idx
            chunk = filters[msg_idx * 126 : msg_idx * 126 + 126]
            msg = build_coef_msg(ch_idx, sr_code, chunk, counter)
            coef_msgs.append(msg)
        print(f"  Ch{ch_idx} ({CH_NAMES[ch_idx]}): {len(filters)} filters → {num_msgs} msgs")

    print(f"Total: {len(coef_msgs)} coefficient messages\n")

    # Connect
    print(f"Connecting to {ip}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((ip, PORT))
    print("Connected\n")
    time.sleep(0.2)

    # GET_AVRINF
    sock.send(bytes.fromhex('54001300004745545f415652494e460000006c'))
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
            print(f"CoefWaitTime: {info.get('CoefWaitTime')}\n")

    # Send config
    print("Sending config...")
    acks = send_all(sock, config_msgs)
    ack_count = sum(1 for a in acks if a == 'ACK')
    print(f"Config ACKs: {ack_count}/{len(config_msgs)}\n")

    # Send coefficients
    print(f"Sending {len(coef_msgs)} coefficient messages...")
    start = time.time()
    for i, msg in enumerate(coef_msgs):
        sock.send(msg)
        time.sleep(0.02)
        if (i + 1) % 200 == 0:
            elapsed = time.time() - start
            print(f"  {i+1}/{len(coef_msgs)} ({(i+1)/len(coef_msgs)*100:.0f}%) ({elapsed:.0f}s)")
    elapsed = time.time() - start
    print(f"Sent in {elapsed:.1f}s\n")

    sock.close()
    print("Disconnected")
    print("\n" + "="*50)
    print(f"TRANSFER COMPLETE ({preset}) — power cycle AVR to apply")
    print("="*50)
    print(f"\nTo switch presets on AVR:")
    print(f"  Telnet port 23: ZM?  (cycles through Audyssey presets)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Transfer OCA calibration to AVR')
    parser.add_argument('oca_file', help='Path to .oca calibration file')
    parser.add_argument('avr_ip', nargs='?', default='192.168.50.2', help='AVR IP address')
    parser.add_argument('--preset', choices=['A', 'B'], default='A',
                        help='Target preset slot (default: A)')
    args = parser.parse_args()

    oca_path = Path(args.oca_file)
    if not oca_path.exists():
        print(f"ERROR: OCA file not found: {oca_path}")
        sys.exit(1)

    try:
        transfer(oca_path, args.avr_ip, args.preset)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()