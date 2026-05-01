#!/usr/bin/env python3
"""
avr_proto_v14.py — Final comprehensive test

Key findings so far:
1. GET_AVRINF → SUCCESS | EQType=MultEQXT32 ✓
2. GET_AVRSTS → SUCCESS but echoes "ERROR" (timing bug, skip it)
3. ENTER_AUDY → SUCCESS but Comm=NACK (calibration mode not entered)
4. SET_SETDAT AmpAssign → SUCCESS | Comm=ACK ✓ (config accepted!)
5. FINZ_COEFS → SUCCESS but Comm=NACK (finalize rejected)

Strategy: Try skipping ENTER_AUDY entirely and go straight to SET_SETDAT AmpAssign,
then FINZ_COEFS. If the calibration mode is auto-entered when we send config,
FINZ_COEFS might work.
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

def get_comm(result):
    if isinstance(result, list) and len(result) > 0:
        return result[0].get('Comm')
    elif isinstance(result, dict):
        return result.get('Comm')
    return None

def send(sock, name, data, delay=0.25):
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

print("=" * 60)
print("TEST 1: Skip ENTER_AUDY, go straight to config")
print("GET_AVRINF → SET_SETDAT AmpAssign → FINZ_COEFS")
print("=" * 60)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(15)
sock.connect((IP, PORT))
time.sleep(0.2)

msg = bytes.fromhex('54001300004745545f415652494e460000006c')
resp = send(sock, 'GET_AVRINF', msg)
mtype, echoed, result = parse_resp(resp)
info = result[0] if isinstance(result, list) else result
print(f"GET_AVRINF: {mtype} | EQType={info.get('EQType','?') if isinstance(info, dict) else '?'}")

msg = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
resp = send(sock, 'SET_SETDAT', msg)
mtype, echoed, result = parse_resp(resp)
print(f"SET_SETDAT AmpAssign: {mtype} | Comm={get_comm(result)}")

msg = bytes.fromhex('541613000846494e5a5f434f45465300000000')
resp = send(sock, 'FINZ_COEFS', msg)
mtype, echoed, result = parse_resp(resp)
print(f"FINZ_COEFS: {mtype} | Comm={get_comm(result)}")

sock.close()
print()

print("=" * 60)
print("TEST 2: Full AcoustiX sequence (without ENTER_AUDY)")
print("GET_AVRINF → SET_SETDAT × all → FINZ_COEFS → FINZ_COEFS")
print("=" * 60)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(15)
sock.connect((IP, PORT))
time.sleep(0.2)

msg = bytes.fromhex('54001300004745545f415652494e460000006c')
resp = send(sock, 'GET_AVRINF', msg)
mtype, echoed, result = parse_resp(resp)
info = result[0] if isinstance(result, list) else result
print(f"GET_AVRINF: {mtype} | EQType={info.get('EQType','?') if isinstance(info, dict) else '?'}")

# SET_SETDAT AmpAssign (11ch)
msg = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
resp = send(sock, 'SET_SETDAT AmpAssign', msg)
mtype, echoed, result = parse_resp(resp)
print(f"SET_SETDAT AmpAssign: {mtype} | Comm={get_comm(result)}")

# SET_SETDAT AudyFinFlg
msg = bytes.fromhex('54002700005345545f5345544441540000137b224164797466696e666c673a46696e227d')
resp = send(sock, 'SET_SETDAT AudyFinFlg', msg)
mtype, echoed, result = parse_resp(resp)
print(f"SET_SETDAT AudyFinFlg: {mtype} | Comm={get_comm(result)}")

# FINZ_COEFS (1st)
msg = bytes.fromhex('541613000846494e5a5f434f45465300000000')
resp = send(sock, 'FINZ_COEFS', msg)
mtype, echoed, result = parse_resp(resp)
print(f"FINZ_COEFS(1): {mtype} | Comm={get_comm(result)}")

# FINZ_COEFS (2nd)
msg = bytes.fromhex('541713000846494e5a5f434f45465300000000')
resp = send(sock, 'FINZ_COEFS(2)', msg)
mtype, echoed, result = parse_resp(resp)
print(f"FINZ_COEFS(2): {mtype} | Comm={get_comm(result)}")

sock.close()
print()

print("=" * 60)
print("TEST 3: Try sending ENTER_AUDY then SET_SETDAT immediately")
print("Without waiting for response — see if responses interleave")
print("=" * 60)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(15)
sock.connect((IP, PORT))
time.sleep(0.2)

msg = bytes.fromhex('54001300004745545f415652494e460000006c')
sock.send(msg)
time.sleep(0.15)
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
info = result[0] if isinstance(result, list) else result
print(f"GET_AVRINF: {mtype} | EQType={info.get('EQType','?') if isinstance(info, dict) else '?'}")

# Send ENTER_AUDY and don't wait fully
msg = bytes.fromhex('5412130000454e5445525f415544590000000000')
sock.send(msg)
time.sleep(0.3)

# Immediately send SET_SETDAT AmpAssign before reading ENTER_AUDY response
msg2 = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
sock.send(msg2)
time.sleep(0.3)

# Now read both responses
resp = b''
try:
    while True:
        chunk = sock.recv(8192)
        if not chunk: break
        resp += chunk
except socket.timeout:
    pass

# Parse first response (should be ENTER_AUDY)
mtype1, echoed1, result1 = parse_resp(resp)
comm1 = get_comm(result1)
print(f"ENTER_AUDY: {mtype1} | echo={echoed1} | Comm={comm1}")

# Find SET_SETDAT response in the raw bytes
ascii_str = resp.decode('ascii', errors='replace')
# Look for the second JSON object
brace_positions = [i for i, c in enumerate(ascii_str) if c == '{']
if len(brace_positions) >= 2:
    second_json = ascii_str[brace_positions[1]:ascii_str.rfind('}')+1]
    try:
        obj2 = json.loads(second_json)
        comm2 = obj2.get('Comm', obj2.get('echo', '?'))
        print(f"SET_SETDAT (after ENTER_AUDY): Comm={comm2}")
    except:
        print(f"SET_SETDAT (after ENTER_AUDY): could not parse second JSON")
elif len(brace_positions) == 1:
    print(f"SET_SETDAT: only 1 JSON found (ENTER_AUDY response), response may be combined")
    # Try looking at raw hex for SET_SETDAT response
    idx = resp.find(b'SET_SETDA')
    if idx >= 0:
        print(f"  SET_SETDAT echoed at index {idx} in response")

sock.close()
print()

print("=" * 60)
print("TEST 4: Check if port 23 has AUDYX commands")
print("=" * 60)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(10)
try:
    sock.connect((IP, 23))
    time.sleep(0.3)

    # Try various Audyssey-related commands on port 23
    cmds = [b'SSDAUDYX ?\r', b'AUDYX ?\r', b'AUDEQ ?\r', b'AUDY ?\r']
    for cmd in cmds:
        sock.send(cmd)
        time.sleep(0.3)
        resp = b''
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk: break
                resp += chunk
        except socket.timeout:
            pass
        if resp:
            clean = resp.decode('ascii', errors='replace').strip()
            if clean:
                print(f"Port 23 {cmd.strip()}: {clean}")
except Exception as e:
    print(f"Port 23 error: {e}")
sock.close()

print()
print("=" * 60)
print("ALL TESTS COMPLETE")
print("=" * 60)