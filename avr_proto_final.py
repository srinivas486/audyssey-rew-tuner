#!/usr/bin/env python3
"""
avr_proto_final.py — Comprehensive protocol test
Tests all discovery findings in sequence until we crack it.
"""
import socket, sys, time, json

IP = "192.168.50.2"
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

def get_comm(result):
    if isinstance(result, list) and len(result) > 0:
        return result[0].get('Comm')
    elif isinstance(result, dict):
        return result.get('Comm')
    return None

# ============================================================
# TEST: Single connection with GET_AVRINF → ENTER_AUDY → SET_SETDAT
# ============================================================
print("=" * 60)
print("TEST 1: GET_AVRINF → ENTER_AUDY (2x) → SET_SETDAT")
print("=" * 60)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(15)
sock.connect((IP, PORT))
print("Connected\n")
time.sleep(0.2)

# GET_AVRINF
msg = bytes.fromhex('54001300004745545f415652494e460000006c')
resp = send(sock, 'GET_AVRINF', msg)
mtype, echoed, result = parse_resp(resp)
info = result[0] if isinstance(result, list) else result
print(f"GET_AVRINF: {mtype} | EQType={info.get('EQType','?') if isinstance(info, dict) else '?'}")

# ENTER_AUDY (1st)
msg = bytes.fromhex('5412130000454e5445525f415544590000000000')
resp = send(sock, 'ENTER_AUDY', msg)
mtype, echoed, result = parse_resp(resp)
print(f"ENTER_AUDY(1): {mtype} | echo={echoed} | Comm={get_comm(result)}")

# ENTER_AUDY (2nd)
msg = bytes.fromhex('5413120000454e5445525f415544590000000000')
resp = send(sock, 'ENTER_AUDY', msg)
mtype, echoed, result = parse_resp(resp)
print(f"ENTER_AUDY(2): {mtype} | echo={echoed} | Comm={get_comm(result)}")

# SET_SETDAT AmpAssign
msg = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
resp = send(sock, 'SET_SETDAT', msg)
mtype, echoed, result = parse_resp(resp)
print(f"SET_SETDAT AmpAssign: {mtype} | echo={echoed} | Comm={get_comm(result)}")

# FINZ_COEFS
msg = bytes.fromhex('541613000846494e5a5f434f45465300000000')
resp = send(sock, 'FINZ_COEFS', msg)
mtype, echoed, result = parse_resp(resp)
print(f"FINZ_COEFS: {mtype} | echo={echoed} | Comm={get_comm(result)}")

sock.close()
print()

# ============================================================
# TEST 2: Two connections — Connection 1 activates, Connection 2 sends config
# ============================================================
print("=" * 60)
print("TEST 2: Two-connection test (activate then reconnect)")
print("=" * 60)

# Connection 1: activate calibration
sock1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock1.settimeout(15)
sock1.connect((IP, PORT))
time.sleep(0.2)

msg = bytes.fromhex('54001300004745545f415652494e460000006c')
resp = send(sock1, 'GET_AVRINF', msg)
mtype, echoed, result = parse_resp(resp)
print(f"Conn1 GET_AVRINF: {mtype} | EQType={result[0].get('EQType','?') if isinstance(result, list) else '?'}")

msg = bytes.fromhex('5412130000454e5445525f415544590000000000')
resp = send(sock1, 'ENTER_AUDY', msg)
mtype, echoed, result = parse_resp(resp)
print(f"Conn1 ENTER_AUDY: {mtype} | Comm={get_comm(result)}")

sock1.close()
print("Conn1 closed (calibration should persist?)")
time.sleep(0.5)

# Connection 2: send config
sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock2.settimeout(15)
sock2.connect((IP, PORT))
time.sleep(0.2)

msg = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
resp = send(sock2, 'SET_SETDAT AmpAssign', msg)
mtype, echoed, result = parse_resp(resp)
print(f"Conn2 SET_SETDAT AmpAssign: {mtype} | Comm={get_comm(result)}")

msg = bytes.fromhex('541613000846494e5a5f434f45465300000000')
resp = send(sock2, 'FINZ_COEFS', msg)
mtype, echoed, result = parse_resp(resp)
print(f"Conn2 FINZ_COEFS: {mtype} | Comm={get_comm(result)}")

sock2.close()
print()

# ============================================================
# TEST 3: Try raw text commands on port 1256
# ============================================================
print("=" * 60)
print("TEST 3: Raw ASCII text on port 1256")
print("=" * 60)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(15)
sock.connect((IP, PORT))
time.sleep(0.3)

sock.send(b'GET_AVRINF\r')
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
print(f"Raw 'GET_AVRINF\\r': {resp[:100].hex() if resp else 'no response'}")
try:
    ascii_str = resp.decode('ascii', errors='replace')
    bp = ascii_str.find('{')
    if bp >= 0:
        obj = json.loads(ascii_str[bp:])
        print(f"  JSON: {obj}")
except:
    pass

sock.close()
print()

# ============================================================
# TEST 4: Check port 23 for Audyssey enable command
# ============================================================
print("=" * 60)
print("TEST 4: Port 23 Telnet commands")
print("=" * 60)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(10)
try:
    sock.connect((IP, 23))
    time.sleep(0.3)
    sock.send(b'?\r')
    time.sleep(0.3)
    resp = b''
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk: break
            resp += chunk
    except socket.timeout:
        pass
    print(f"Port 23 '?': {resp.decode('ascii', errors='replace').strip()}")
    sock.send(b'ZM?\r')
    time.sleep(0.3)
    resp = b''
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk: break
            resp += chunk
    except socket.timeout:
        pass
    print(f"Port 23 'ZM?': {resp.decode('ascii', errors='replace').strip()}")
    sock.send(b'SSDAUDYX?\r')
    time.sleep(0.3)
    resp = b''
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk: break
            resp += chunk
    except socket.timeout:
        pass
    print(f"Port 23 'SSDAUDYX?': {resp.decode('ascii', errors='replace').strip()}")
except Exception as e:
    print(f"Port 23 error: {e}")

sock.close()
print()
print("=" * 60)
print("ALL TESTS COMPLETE")
print("=" * 60)