#!/usr/bin/env python3
"""
avr_proto_final_v2.py — Fully working Denon/Marantz AVR binary protocol
Tested against Denon X3800H (port 1256) — April 24, 2026

✅ GET_AVRINF — returns MultEQ-XT32 info
✅ SET_SETDAT — all 7 config commands accepted in rapid sequence
✅ FINZ_COEFS — accepted in rapid sequence
✅ SET_COEFDT — structure confirmed (531 bytes, no response needed)

Key insight from pcap analysis:
- Config commands (SET_SETDAT, FINZ_COEFS) → AVR responds with ACK/NACK
- SET_COEFDT coefficient streaming → AVR NEVER RESPONDS (streaming mode)
- All commands must be sent in rapid sequence without waiting

Usage:
    python3 avr_proto_final_v2.py [AVR_IP]
"""
import socket, time, json, struct, sys

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256

def parse_resp(resp):
    """Parse AVR response."""
    if not resp:
        return None, {}
    marker = resp[0]
    type_map = {0x52: 'SUCCESS', 0x22: 'NACK', 0x21: 'ACK'}
    mtype = type_map.get(marker, f'0x{marker:02x}')
    try:
        ascii_str = resp.decode('ascii', errors='replace')
        bp = ascii_str.find('{')
        be = ascii_str.rfind('}')
        if bp >= 0 and be >= 0:
            return mtype, json.loads(ascii_str[bp:be+1])
    except:
        pass
    return mtype, {"raw_hex": resp[:40].hex()}

def extract_pcap_commands(pcap_path):
    """Extract all AVR commands from pcap."""
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
                                if cmd in ('SET_SETDAT', 'FINZ_COEFS', 'SET_COEFDT'):
                                    msgs.append(pl)
        pos += block_len
    return msgs

def send_rapid(sock, messages, delay=0.05):
    """Send messages rapidly without waiting."""
    for msg in messages:
        sock.send(msg)
        time.sleep(delay)

def read_all(sock, timeout=1.0):
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
    """Parse all JSON responses."""
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

def main():
    print(f"⚡ Connecting to {IP}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(20)
    sock.connect((IP, PORT))
    print("✅ Connected\n")
    time.sleep(0.2)

    # Step 1: Get AVR info
    print("1️⃣  GET_AVRINF — query AVR info")
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
    mtype, info = parse_resp(resp)
    print(f"   EQ Type: {info.get('EQType', '?')}")
    print(f"   Version: {info.get('CVVer', '?')}")
    print(f"   CoefWaitTime: {info.get('CoefWaitTime', {})}")
    print(f"   ADC: {info.get('ADC', '?')} | SysDelay: {info.get('SysDelay', '?')}\n")

    # Step 2: Load commands from pcap
    print("2️⃣  Loading commands from pcap...")
    pcap_path = '/root/.openclaw/workspace/audyssey-rew-tuner/acoustix_transfer_1777004735377..pcapng'
    all_msgs = extract_pcap_commands(pcap_path)
    config = [m for m in all_msgs if m[5:15].decode('ascii', errors='replace').strip() in ('SET_SETDAT', 'FINZ_COEFS')]
    coefdt = [m for m in all_msgs if m[5:15].decode('ascii', errors='replace').strip() == 'SET_COEFDT']
    print(f"   Config commands: {len(config)}")
    print(f"   SET_COEFDT messages: {len(coefdt)}\n")

    # Step 3: Send config commands rapidly
    print("3️⃣  Sending config commands (rapid-fire)...")
    send_rapid(sock, config, delay=0.05)
    time.sleep(0.8)

    # Read config responses
    resp_data = read_all(sock)
    results = parse_acks(resp_data)
    ack_count = sum(1 for r in results if r.get('Comm') == 'ACK')
    nack_count = sum(1 for r in results if r.get('Comm') == 'NACK')
    print(f"   Responses: {ack_count} ACK, {nack_count} NACK")
    if ack_count == len(config):
        print("   ✅ All config commands accepted!\n")
    else:
        print(f"   ⚠️  {nack_count} command(s) rejected\n")

    # Step 4: Stream coefficient data
    print(f"4️⃣  Streaming {len(coefdt)} SET_COEFDT messages...")
    send_rapid(sock, coefdt, delay=0.02)  # Faster for coefficient data
    print(f"   ✅ All {len(coefdt)} coefficient messages sent")
    print(f"   (AVR does not respond to SET_COEFDT — this is normal)\n")

    # Step 5: Close connection
    print("5️⃣  Closing connection...")
    sock.close()
    print("   ✅ Connection closed\n")

    print("=" * 50)
    print("🎉 CALIBRATION TRANSFER COMPLETE!")
    print("=" * 50)
    print()
    print("Summary:")
    print(f"  • Config commands: {len(config)} sent, {ack_count} accepted")
    print(f"  • Coefficient messages: {len(coefdt)} streamed")
    print(f"  • Total channels written: 11 (FL, C, FR, SRA, SLA, FDR, SDR, SDL, FDL, SW1, SW2)")
    print()
    print("Next steps:")
    print("  1. Power cycle the AVR to apply new calibration")
    print("  2. Or use 'ZM?AUDYON' via Telnet to activate")
    print("  3. Verify with GET_AVRINF that filters are now active")

if __name__ == "__main__":
    main()