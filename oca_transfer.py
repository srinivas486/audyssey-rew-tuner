#!/usr/bin/env python3
"""
oca_transfer.py — Transfer full OCA calibration to Denon/Marantz AVR

PROTOCOL: Binary TCP on port 1256
CONFIRMED: April 24, 2026

Key findings:
  - Coefficient encoding: LITTLE-ENDIAN float32
  - Coefficient offset: TCP payload offset 22
  - TCP payload structure:
      marker(1) + counter(3) + flag(1) + cmd(10) + null(1)
      + meta(4) + channel(1) + SR(1) + coefs(504)

Usage:
    python3 oca_transfer.py [IP]
    python3 oca_transfer.py 192.168.50.2
"""
import json, struct, socket, time, sys
from pathlib import Path

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256

# ─── Protocol constants ────────────────────────────────────────────────────────

MARKER = 0x54          # 'T'
FLAG_SET_COEF = 0x08   # data transfer flag
META_COEF = bytes([0x02, 0x00, 0x01, 0x00])  # always this for SET_COEFDT
SR_CODE = {32000: 0, 44100: 52, 48000: 57, 96000: 184}

# Channel indices (Denon/Marantz MultEQ-XT32)
CH_NAMES = ['FL', 'C', 'FR', 'SBR', 'SBL', 'FHL', 'FHR', 'SW1', 'SW2', 'FDL', 'FDR']

# ─── Data files ───────────────────────────────────────────────────────────────

HERE = Path(__file__).parent

# OCA file from the verified Apr24_1844 run
OCA_FILE = HERE / "A1EvoAcoustiX_Apr24_1844_1777065760128..oca"

# pcap from the same run — config bytes embedded here have correct SW trim values
PCAP_FILE = HERE / "acoustix_transfer_1777065760128..pcapng"


# ─── Helpers ─────────────────────────────────────────────────────────────────

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


def extract_config_msgs(data):
    """Extract SET_SETDAT config messages from pcap."""
    msgs = []
    for _bn, _fp, tcp in pcap_reader(data):
        cmd = tcp[5:15].decode('ascii', errors='replace').strip()
        if cmd == 'SET_SETDAT':
            msgs.append(tcp)
    return msgs


def build_coef_msg(channel, sr_code, coefficients, counter):
    """Build a 531-byte SET_COEFDT message."""
    coef_bytes = b''
    for c in coefficients:
        coef_bytes += struct.pack('<f', float(c))   # LE float32 ✓
    coef_bytes += bytes(504 - len(coef_bytes))       # pad to 504 bytes

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


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"=== OCA Transfer ===")
    print(f"Target: {IP}:{PORT}\n")

    # Load calibration
    with open(OCA_FILE, 'r') as f:
        oca = json.load(f)
    print(f"OCA: {oca['model']} | {len(oca['channels'])} channels | eqType={oca['eqType']}")
    for i, ch in enumerate(oca['channels']):
        print(f"  Ch{i} ({CH_NAMES[i]}): {len(ch['filter'])} filters"
              f" | trim={ch['trimAdjustmentInDbs']}dB | dist={ch['distanceInMeters']}m")

    # Extract config from pcap
    with open(PCAP_FILE, 'rb') as f:
        pcap_data = f.read()
    config_msgs = extract_config_msgs(pcap_data)
    print(f"\nConfig messages: {len(config_msgs)}")

    # Build coefficient messages
    print("\nBuilding coefficient messages...")
    coef_msgs = []
    counter_base = 0x1300

    for ch_idx, ch_data in enumerate(oca['channels']):
        filters = ch_data['filter']
        num_msgs = (len(filters) + 125) // 126
        for msg_idx in range(num_msgs):
            counter = counter_base + (msg_idx << 8) + ch_idx
            chunk = filters[msg_idx * 126 : msg_idx * 126 + 126]
            msg = build_coef_msg(ch_idx, 0, chunk, counter)
            coef_msgs.append(msg)
        print(f"  Ch{ch_idx} ({CH_NAMES[ch_idx]}): {len(filters)} filters → {num_msgs} msgs")

    print(f"Total: {len(coef_msgs)} coefficient messages\n")

    # Connect
    print(f"Connecting to {IP}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((IP, PORT))
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
            print(f"  {i+1}/{len(coef_msgs)} ({(i+1)/len(coef_msgs)*100:.0f}%)")
    elapsed = time.time() - start
    print(f"Sent in {elapsed:.1f}s\n")

    sock.close()
    print("Disconnected")
    print("\n" + "="*50)
    print("TRANSFER COMPLETE — power cycle AVR to apply")
    print("="*50)


if __name__ == '__main__':
    main()
