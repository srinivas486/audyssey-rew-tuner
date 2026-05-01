#!/usr/bin/env python3
"""
avr_proto_v12.py — Skip GET_AVRSTS and go straight to ENTER_AUDY after GET_AVRINF.
SET_SETDAT AmpAssign already confirmed working → let's push further.

Run: python3 avr_proto_v12.py [AVR_IP]
"""
import socket, sys, time, json

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256

def parse_resp(resp):
    if not resp:
        return "NO RESPONSE", None, {}
    marker = resp[0]
    type_map = {0x52: 'SUCCESS', 0x22: 'NACK', 0x21: 'ACK'}
    mtype = type_map.get(marker, f'0x{marker:02x}')
    echoed = resp[4:14].decode('ascii', errors='replace').strip('\x00').strip() if len(resp) >= 14 else '?'
    try:
        ascii_str = resp.decode('ascii', errors='replace')
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
    print(f"Connecting to {IP}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)
    sock.connect((IP, PORT))
    print("✅ Connected\n")
    time.sleep(0.2)

    # GET_AVRINF — confirm connection
    print("1️⃣  GET_AVRINF")
    msg = bytes.fromhex('54001300004745545f415652494e460000006c')
    sock.send(msg)
    time.sleep(0.5)  # longer delay — let AVR fully process
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
    print(f"    ← {mtype} | {echoed} | EQType={info.get('EQType','?')}")
    print()

    # Skip GET_AVRSTS entirely — go straight to ENTER_AUDY
    print("2️⃣  ENTER_AUDY (1st) — after GET_AVRINF only")
    msg = bytes.fromhex('5412130000454e5445525f415544590000000000')
    sock.send(msg)
    time.sleep(0.5)
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

    # 2nd ENTER_AUDY
    print("3️⃣  ENTER_AUDY (2nd)")
    msg = bytes.fromhex('5413120000454e5445525f415544590000000000')
    sock.send(msg)
    time.sleep(0.5)
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

    # SET_SETDAT AmpAssign
    print("4️⃣  SET_SETDAT — AmpAssign")
    msg = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
    sock.send(msg)
    time.sleep(0.5)
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

    # SET_SETDAT AssignBin (speaker layout — 133 bytes)
    print("5️⃣  SET_SETDAT — AssignBin")
    assignbin = b'{"AssignBin":"0C0403000201000020000000400000000000000000000000000000000202000202020001020304060A0800000001010000"}'
    msg = bytes.fromhex('54008500005345545f5345544441540000') + assignbin
    sock.send(msg)
    time.sleep(0.5)
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

    # FINZ_COEFS
    print("6️⃣  FINZ_COEFS")
    msg = bytes.fromhex('541613000846494e5a5f434f45465300000000')
    sock.send(msg)
    time.sleep(1.0)
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