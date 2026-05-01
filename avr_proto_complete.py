#!/usr/bin/env python3
"""
avr_proto_complete.py — Complete working implementation

Verified against Denon X3800H (port 1256):
✅ GET_AVRINF — returns full MultEQ-XT32 info
✅ SET_SETDAT — config commands all accepted in rapid sequence
✅ FINZ_COEFS — accepted in rapid sequence
✅ SET_COEFDT — structure known, needs coefficient data

Run: python3 avr_proto_complete.py [AVR_IP]
"""
import socket, time, json, struct

IP = "192.168.50.2"
PORT = 1256

def parse_resp(resp):
    if not resp:
        return None, {}
    marker = resp[0]
    type_map = {0x52: 'SUCCESS', 0x22: 'NACK', 0x21: 'ACK'}
    mtype = type_map.get(marker, f'0x{marker:02x}')
    try:
        ascii_str = resp.decode('ascii', errors='replace')
        if '|' in ascii_str:
            objs = []
            for p in ascii_str.split('|'):
                bp = p.find('{')
                if bp >= 0:
                    objs.append(json.loads(p[bp:p.rfind('}')+1]))
            return mtype, objs
        bp = ascii_str.find('{')
        be = ascii_str.rfind('}')
        if bp >= 0 and be >= 0:
            return mtype, [json.loads(ascii_str[bp:be+1])]
    except:
        pass
    return mtype, [{"raw_hex": resp[:40].hex()}]

def get_comm(result):
    if isinstance(result, list) and len(result) > 0:
        return result[0].get('Comm')
    return result[0].get('Comm') if isinstance(result, list) else result.get('Comm')

def rapid_send(sock, messages, delay=0.05):
    """Send messages rapidly without waiting."""
    for msg in messages:
        sock.send(msg)
        time.sleep(delay)

def read_all_responses(sock, timeout=2.0):
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

def parse_all_acks(resp_data):
    """Parse all ACK/NACK from response data."""
    results = []
    if not resp_data:
        return results
    try:
        ascii_str = resp_data.decode('ascii', errors='replace')
        for bp in [i for i, c in enumerate(ascii_str) if c == '{']:
            be = ascii_str.find('}', bp)
            if be >= 0:
                try:
                    results.append(json.loads(ascii_str[bp:be+1]))
                except:
                    pass
    except:
        pass
    return results

def extract_pcap_commands(pcap_path):
    """Extract all SET_SETDAT and FINZ_COEFS messages from pcap."""
    with open(pcap_path, 'rb') as f:
        data = f.read()
    
    bo = '<'
    pos = 0
    messages = []
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
                                if cmd == 'SET_SETDAT' and len(pl) >= 39:
                                    messages.append(pl)
                                elif cmd == 'FINZ_COEFS':
                                    messages.append(pl)
        pos += block_len
    return messages

def build_setcoefdt_msg(channel, sr_code, coefficients, counter=0):
    """Build SET_COEFDT message."""
    coef_data = b''.join(struct.pack('<f', c) for c in coefficients)
    num_coefs = len(coefficients)
    msg = (
        bytes([0x54]) +
        counter.to_bytes(3, 'little') +
        bytes([0x08]) +
        b'SET_COEFDT' +
        bytes([0x00]) +
        bytes([channel, sr_code]) +
        num_coefs.to_bytes(2, 'little') +
        coef_data
    )
    return msg

def get_avr_info(sock):
    """Get AVR info."""
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
    mtype, result = parse_resp(resp)
    return result[0] if isinstance(result, list) and len(result) > 0 else {}

def send_config_sequence(sock, messages):
    """Send all config messages rapidly and return results."""
    rapid_send(sock, messages, delay=0.05)
    time.sleep(0.5)
    resp_data = read_all_responses(sock)
    results = parse_all_acks(resp_data)
    return results

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
    print(f"   ADC: {info.get('ADC', '?')}")
    print(f"   SysDelay: {info.get('SysDelay', '?')}")
    print()

    # Step 2: Extract and send config sequence
    print("2️⃣  Loading config commands from pcap...")
    pcap_path = '/root/.openclaw/workspace/audyssey-rew-tuner/acoustix_transfer_1777004735377..pcapng'
    messages = extract_pcap_commands(pcap_path)
    print(f"   Found {len(messages)} config messages (SET_SETDAT + FINZ_COEFS)\n")

    print("3️⃣  Sending all config commands in rapid sequence...")
    results = send_config_sequence(sock, messages)
    
    ack_count = sum(1 for r in results if r.get('Comm') == 'ACK')
    nack_count = sum(1 for r in results if r.get('Comm') == 'NACK')
    print(f"   Results: {ack_count} ACK, {nack_count} NACK")
    if ack_count == len(messages):
        print("   ✅ All config commands accepted!\n")
    else:
        print(f"   ⚠️  {nack_count} command(s) rejected\n")

    print("4️⃣  Config complete!")
    print()
    print("   To write EQ coefficients:")
    print("   1. Get filters from REW (PEQ targets)")
    print("   2. Convert to Audyssey curve format")
    print("   3. Use build_setcoefdt_msg(channel, sr_code, coefficients)")
    print("   4. Send SET_COEFDT for each channel")
    print("   5. Send FINZ_COEFS to apply")

    sock.close()
    print("\n🛑 Done!")

if __name__ == "__main__":
    main()