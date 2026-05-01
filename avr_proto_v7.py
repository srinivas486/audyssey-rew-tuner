#!/usr/bin/env python3
"""
avr_proto_v7.py — Send EXACT AcoustiX bytes with ZERO delay between commands.
The AVR might need commands sent in rapid succession (like AcoustiX does).
Run: python3 avr_proto_v7.py [AVR_IP]
"""
import socket, sys, time, json

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256

# Exact AcoustiX bytes from pcap (first few commands only)
COMMANDS = [
    ('GET_AVRINF',  bytes.fromhex('54001300004745545f415652494e460000006c')),
    ('GET_AVRSTS',  bytes.fromhex('540a130000474554415652535453000000730000')),
    ('ENTER_AUDY',  bytes.fromhex('5412130000454e5445525f415544590000000000')),
    ('ENTER_AUDY2', bytes.fromhex('5413120000454e5445525f415544590000000000')),
]

def send_raw(sock, name, data):
    """Send exact bytes, parse response."""
    sock.send(data)
    time.sleep(0.05)  # minimal delay

    resp = b''
    sock.settimeout(8)
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass
    return resp

def parse_resp(resp):
    if not resp:
        return "NO RESPONSE", None, None
    marker = resp[0]
    type_map = {0x52: 'SUCCESS', 0x22: 'NACK', 0x21: 'ACK'}
    mtype = type_map.get(marker, f'0x{marker:02x}')
    echoed = resp[4:12].decode('ascii', errors='replace').strip('\x00').strip() if len(resp) >= 12 else '?'
    try:
        ascii_str = resp.decode('ascii', errors='replace')
        brace_pos = ascii_str.find('{')
        brace_end = ascii_str.rfind('}')
        if brace_pos >= 0 and brace_end >= 0:
            obj = json.loads(ascii_str[brace_pos:brace_end+1])
            return mtype, echoed, obj
    except:
        pass
    return mtype, echoed, resp[:30].hex()

def main():
    print(f"Connecting to {IP}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)
    sock.connect((IP, PORT))
    print("✅ Connected\n")
    time.sleep(0.1)

    for name, data in COMMANDS:
        print(f"→ {name}: {data.hex()}")
        resp = send_raw(sock, name, data)
        mtype, echoed, obj = parse_resp(resp)
        if isinstance(obj, dict):
            print(f"  ← {mtype} | {echoed} | {obj}")
        else:
            print(f"  ← {mtype} | {echoed} | {obj}")
        print()

    sock.close()
    print("🛑 Done")

if __name__ == "__main__":
    main()