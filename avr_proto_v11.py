#!/usr/bin/env python3
"""
avr_proto_v11.py — Replicate EXACT AcoustiX command sequence
The only difference is we don't send the 12-byte handshake (since it returns ERROR).

Strategy: follow the EXACT sequence from pcap with proper timing,
and test ENTER_AUDY after GET_AVRINF + GET_AVRSTS (no handshake needed).

Run: python3 avr_proto_v11.py [AVR_IP]
"""
import socket, sys, time, json

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256
_counter = 0x1313  # Match AcoustiX starting counter

# Build messages exactly like AcoustiX
def build_msg(cmd_name, has_data=False, meta_len=3, json_data=b''):
    global _counter
    _counter += 1
    counter = _counter.to_bytes(3, 'little')
    cmd_bytes = cmd_name.encode('ascii').ljust(10, b' ')
    cmd_flag = b'\x08' if has_data else b'\x00'
    # Meta: \x00\x00 followed by length byte (for SET_SETDAT style)
    if has_data:
        meta = b'\x00\x00' + bytes([len(json_data)])
    else:
        meta = b'\x00' * meta_len
    header = b'T' + counter + cmd_flag + cmd_bytes + b'\x00' + meta
    return header + json_data

def parse_resp(resp):
    if not resp:
        return "NO RESPONSE", None, {}
    marker = resp[0]
    type_map = {0x52: 'SUCCESS', 0x22: 'NACK', 0x21: 'ACK'}
    mtype = type_map.get(marker, f'0x{marker:02x}')
    echoed = resp[4:14].decode('ascii', errors='replace').strip('\x00').strip() if len(resp) >= 14 else '?'
    try:
        ascii_str = resp.decode('ascii', errors='replace')
        # Split by | for multi-JSON responses
        if '|' in ascii_str:
            objs = []
            for p in ascii_str.split('|'):
                bp = p.find('{')
                if bp >= 0:
                    objs.append(json.loads(p[bp:p.rfind('}')+1]))
            return mtype, echoed, objs
        bp = ascii_str.find('{')
        be = ascii_str.rfind('}')
        if bp >= 0 and be >= 0:
            return mtype, echoed, json.loads(ascii_str[bp:be+1])
    except:
        pass
    return mtype, echoed, {"raw_hex": resp[:40].hex()}

def send(sock, name, data, delay=0.15):
    sock.send(data)
    time.sleep(delay)
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

def main():
    global _counter
    _counter = 0x1312  # Will be incremented to 0x1313 on first send

    print(f"Connecting to {IP}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)
    sock.connect((IP, PORT))
    print("✅ Connected\n")
    time.sleep(0.2)

    # Step 1: GET_AVRINF (exact AcoustiX bytes)
    print("1️⃣  GET_AVRINF")
    msg = bytes.fromhex('54001300004745545f415652494e460000006c')
    print(f"    → {msg.hex()}")
    sock.send(msg)
    time.sleep(0.2)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass
    mtype, echoed, result = parse_resp(resp)
    info = result[0] if isinstance(result, list) else (result if isinstance(result, dict) else {})
    if info.get('EQType'):
        print(f"    ← {mtype} | {echoed} | EQType={info['EQType']} ✅")
    else:
        print(f"    ← {mtype} | {echoed} | {result}")
    print()

    # Step 2: GET_AVRSTS
    print("2️⃣  GET_AVRSTS")
    msg = bytes.fromhex('540a130000474554415652535453000000730000')
    print(f"    → {msg.hex()}")
    sock.send(msg)
    time.sleep(0.2)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass
    mtype, echoed, result = parse_resp(resp)
    info = result[0] if isinstance(result, list) else (result if isinstance(result, dict) else {})
    if info.get('AmpAssign'):
        print(f"    ← {mtype} | {echoed} | AmpAssign={info['AmpAssign']} ✅")
    else:
        print(f"    ← {mtype} | {echoed} | {result}")
    print()

    # Step 3: ENTER_AUDY (1st call)
    print("3️⃣  ENTER_AUDY (1st)")
    msg = bytes.fromhex('5412130000454e5445525f415544590000000000')
    print(f"    → {msg.hex()}")
    sock.send(msg)
    time.sleep(0.2)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass
    mtype, echoed, result = parse_resp(resp)
    comm = None
    if isinstance(result, list) and len(result) > 0:
        comm = result[0].get('Comm')
    elif isinstance(result, dict):
        comm = result.get('Comm')
    print(f"    ← {mtype} | {echoed} | Comm={comm}")
    print()

    # Step 4: ENTER_AUDY (2nd call)
    print("4️⃣  ENTER_AUDY (2nd)")
    msg = bytes.fromhex('5413120000454e5445525f415544590000000000')
    print(f"    → {msg.hex()}")
    sock.send(msg)
    time.sleep(0.2)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass
    mtype, echoed, result = parse_resp(resp)
    comm = None
    if isinstance(result, list) and len(result) > 0:
        comm = result[0].get('Comm')
    elif isinstance(result, dict):
        comm = result.get('Comm')
    print(f"    ← {mtype} | {echoed} | Comm={comm}")
    print()

    # Step 5: SET_SETDAT AmpAssign
    print("5️⃣  SET_SETDAT — AmpAssign")
    msg = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
    print(f"    → {msg.hex()}")
    sock.send(msg)
    time.sleep(0.2)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass
    mtype, echoed, result = parse_resp(resp)
    comm = None
    if isinstance(result, list) and len(result) > 0:
        comm = result[0].get('Comm')
    elif isinstance(result, dict):
        comm = result.get('Comm')
    print(f"    ← {mtype} | {echoed} | Comm={comm}")
    print()

    # Step 6: FINZ_COEFS (to trigger coefficient write)
    print("6️⃣  FINZ_COEFS")
    msg = bytes.fromhex('541613000846494e5a5f434f45465300000000')
    print(f"    → {msg.hex()}")
    sock.send(msg)
    time.sleep(0.2)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass
    mtype, echoed, result = parse_resp(resp)
    comm = None
    if isinstance(result, list) and len(result) > 0:
        comm = result[0].get('Comm')
    elif isinstance(result, dict):
        comm = result.get('Comm')
    print(f"    ← {mtype} | {echoed} | Comm={comm}")
    print()

    sock.close()
    print("🛑 Done")

if __name__ == "__main__":
    main()