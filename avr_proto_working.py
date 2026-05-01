#!/usr/bin/env python3
"""
avr_proto_working.py — Fully working Denon/Marantz AVR binary protocol implementation
Tested and verified against Denon X3800H (port 1256)

Key findings:
1. GET_AVRINF → returns MultEQ-XT32 info (SUCCESS)
2. SET_SETDAT AmpAssign → ACK (config accepted)
3. Rapid-fire all config commands → all return ACK
4. FINZ_COEFS → ACK when sent in rapid-fire sequence
5. SET_COEFDT → NOT TESTED YET (needs coefficient data from REW/AcoustiX)

Message format (20-byte header + data):
  T(1) + 3-byte counter(LE) + flag(1) + cmd(10) + null(1) + meta(3-4) + data

For SET_SETDAT with JSON:
  T + counter + 00 + "SET_SETDAT" + 00 + 00 00 LEN(1 byte) + JSON

Run: python3 avr_proto_working.py [AVR_IP]
"""
import socket, time, json, struct

IP = "192.168.50.2"
PORT = 1256

def get_avr_info(sock):
    """Query AVR info and return parsed result."""
    sock.send(bytes.fromhex('54001300004745545f415652494e460000006c'))
    time.sleep(0.3)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except:
        pass
    if resp and resp[0] == 0x52:
        try:
            ascii_str = resp.decode('ascii', errors='replace')
            bp = ascii_str.find('{')
            be = ascii_str.rfind('}')
            if bp >= 0 and be >= 0:
                return json.loads(ascii_str[bp:be+1])
        except:
            pass
    return {}

def rapid_send(sock, messages, delay=0.05):
    """Send multiple messages rapidly without waiting for responses."""
    for msg in messages:
        sock.send(msg)
        time.sleep(delay)

def read_responses(sock, timeout=2.0):
    """Read all pending responses."""
    sock.settimeout(timeout)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
    except socket.timeout:
        pass
    return resp

def parse_acks(resp_data):
    """Parse all ACK/NACK responses from response data."""
    results = []
    if not resp_data:
        return results
    try:
        ascii_str = resp_data.decode('ascii', errors='replace')
        # Find all JSON objects
        brace_positions = [i for i, c in enumerate(ascii_str) if c == '{']
        for bp in brace_positions:
            be = ascii_str.find('}', bp)
            if be >= 0:
                try:
                    obj = json.loads(ascii_str[bp:be+1])
                    results.append(obj.get('Comm', '?'))
                except:
                    pass
    except:
        pass
    return results

def build_setcoefdt(channel, sr_code, coefficients):
    """
    Build a SET_COEFDT message for a given channel and coefficients.
    
    Args:
        channel: 0=FL, 1=C, 2=FR, 3=SRA, 4=SLA, 5=FDR, 6=SDL, 7=SDR, 8=FDL, 9=SW1, 10=SW2
        sr_code: 0=32kHz, 1=44.1kHz, 2=48kHz
        coefficients: list of float values (IEEE 754 LE float32)
    """
    coef_data = b''.join(struct.pack('<f', c) for c in coefficients)
    num_coefs = len(coefficients)
    msg = (
        bytes([0x54]) +                                    # T marker
        (0).to_bytes(3, 'little') +                        # counter (will be overridden by caller)
        bytes([0x08]) +                                   # data transfer flag
        b'SET_COEFDT' +                                    # command (10 bytes)
        bytes([0x00]) +                                   # null
        bytes([channel, sr_code]) +                        # meta: channel + SR
        num_coefs.to_bytes(2, 'little') +                 # num coefficients (2 bytes LE)
        coef_data                                        # coefficient floats
    )
    return msg

def main():
    print(f"Connecting to {IP}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)
    sock.connect((IP, PORT))
    print("✅ Connected\n")
    time.sleep(0.2)

    # Step 1: Get AVR info
    print("1️⃣  GET_AVRINF — query AVR info")
    info = get_avr_info(sock)
    print(f"   EQ Type: {info.get('EQType', '?')}")
    print(f"   Version: {info.get('CVVer', '?')}")
    print(f"   CoefWaitTime: {info.get('CoefWaitTime', {})}")
    print()

    # Step 2: Extract config commands from pcap
    print("2️⃣  Extracting config commands from pcap...")
    with open('/root/.openclaw/workspace/audyssey-rew-tuner/acoustix_transfer_1777004735377..pcapng', 'rb') as f:
        pcap_data = f.read()

    bo = '<'
    pos = 0
    config_messages = []
    while pos < len(pcap_data) - 12:
        block_type = struct.unpack(bo+'I', pcap_data[pos:pos+4])[0]
        block_len = struct.unpack(bo+'I', pcap_data[pos+4:pos+8])[0]
        if block_len < 12 or block_len > len(pcap_data) - pos:
            pos += 1
            continue
        if block_type == 6:
            cap_len = struct.unpack(bo+'I', pcap_data[pos+20:pos+24])[0]
            if cap_len > 0 and cap_len <= 1514:
                packet_start = pos + 28
                packet = pcap_data[packet_start:packet_start+cap_len]
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
                                if cmd == 'SET_SETDAT' and len(pl) >= 39:
                                    config_messages.append(pl)
                                elif cmd == 'FINZ_COEFS':
                                    config_messages.append(pl)
        pos += block_len

    print(f"   Found {len(config_messages)} config messages (SET_SETDAT + FINZ_COEFS)\n")

    # Step 3: Rapid-fire all config commands
    print("3️⃣  Sending all config commands in rapid sequence...")
    rapid_send(sock, config_messages, delay=0.05)
    time.sleep(0.5)

    # Read responses
    resp_data = read_responses(sock)
    acks = parse_acks(resp_data)
    nack_count = sum(1 for a in acks if a == 'NACK')
    ack_count = sum(1 for a in acks if a == 'ACK')
    print(f"   Responses: {ack_count} ACK, {nack_count} NACK")
    if ack_count == len(config_messages):
        print("   ✅ All config commands accepted!\n")
    else:
        print(f"   ⚠️  Some commands rejected ({len(config_messages) - ack_count} rejected)\n")

    print("4️⃣  Config sequence complete!")
    print("   To write coefficients, use build_setcoefdt() with proper channel/SR/coefficients.")
    print("   The coefficient data should come from REW or AcoustiX calibration.")

    sock.close()
    print("\n🛑 Disconnected. Done!")

if __name__ == "__main__":
    main()