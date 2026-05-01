#!/usr/bin/env python3
"""
avr_proto_v13.py — Two-connection theory test

Theory: AcoustiX uses CONNECTION 1 to enter calibration mode,
then CONNECTION 2 to send config and coefficients.

If the calibration session persists after connection closes,
maybe calling ENTER_AUDY, then closing and reconnecting
will allow subsequent commands to work.

Run: python3 avr_proto_v13.py [AVR_IP]
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

def send(sock, name, data, delay=0.2):
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

def connect():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)
    sock.connect((IP, PORT))
    time.sleep(0.1)
    return sock

print(f"Connecting to {IP}:{PORT}\n")

# === CONNECTION 1: Enter calibration mode ===
print("━━━ CONNECTION 1: Enter calibration mode ━━━\n")
sock1 = connect()
print("✅ Connected\n")

# GET_AVRINF
print("1️⃣  GET_AVRINF")
msg = bytes.fromhex('54001300004745545f415652494e460000006c')
resp = send(sock1, 'GET_AVRINF', msg)
mtype, echoed, result = parse_resp(resp)
info = result[0] if isinstance(result, list) else (result if isinstance(result, dict) else {})
print(f"    {mtype} | {echoed} | EQType={info.get('EQType','?')}")

# ENTER_AUDY
print("\n2️⃣  ENTER_AUDY (enter calibration)")
msg = bytes.fromhex('5412130000454e5445525f415544590000000000')
resp = send(sock1, 'ENTER_AUDY', msg)
mtype, echoed, result = parse_resp(resp)
comm = None
if isinstance(result, list) and len(result) > 0: comm = result[0].get('Comm')
elif isinstance(result, dict): comm = result.get('Comm')
print(f"    {mtype} | {echoed} | Comm={comm}")

# ENTER_AUDY 2nd
print("\n3️⃣  ENTER_AUDY (2nd)")
msg = bytes.fromhex('5413120000454e5445525f415544590000000000')
resp = send(sock1, 'ENTER_AUDY', msg)
mtype, echoed, result = parse_resp(resp)
comm = None
if isinstance(result, list) and len(result) > 0: comm = result[0].get('Comm')
elif isinstance(result, dict): comm = result.get('Comm')
print(f"    {mtype} | {echoed} | Comm={comm}")

print("\n🛑 Closing connection 1 (calibration session should persist)...")
sock1.close()
time.sleep(0.5)

# === CONNECTION 2: Send config (test if calibration mode is still active) ===
print("\n━━━ CONNECTION 2: Test if calibration persists ━━━\n")
sock2 = connect()
print("✅ Connected\n")

# SET_SETDAT AmpAssign
print("4️⃣  SET_SETDAT — AmpAssign")
msg = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
resp = send(sock2, 'SET_SETDAT', msg)
mtype, echoed, result = parse_resp(resp)
comm = None
if isinstance(result, list) and len(result) > 0: comm = result[0].get('Comm')
elif isinstance(result, dict): comm = result.get('Comm')
print(f"    {mtype} | {echoed} | Comm={comm}")

# FINZ_COEFS
print("\n5️⃣  FINZ_COEFS")
msg = bytes.fromhex('541613000846494e5a5f434f45465300000000')
resp = send(sock2, 'FINZ_COEFS', msg)
mtype, echoed, result = parse_resp(resp)
comm = None
if isinstance(result, list) and len(result) > 0: comm = result[0].get('Comm')
elif isinstance(result, dict): comm = result.get('Comm')
print(f"    {mtype} | {echoed} | Comm={comm}")

sock2.close()
print("\n🛑 Done")