#!/usr/bin/env python3
"""
avr_proto_v8.py — Two key theories to test:
1. Connection timing: maybe need longer delay after TCP connect
2. Raw text first: maybe port 1256 accepts ASCII like port 23 does

Run: python3 avr_proto_v8.py [AVR_IP]
"""
import socket, sys, time, json

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256

# Exact AcoustiX bytes
GET_AVRINF   = bytes.fromhex('54001300004745545f415652494e460000006c')
GET_AVRSTS   = bytes.fromhex('540a130000474554415652535453000000730000')
ENTER_AUDY1  = bytes.fromhex('5412130000454e5445525f415544590000000000')
ENTER_AUDY2  = bytes.fromhex('5413120000454e5445525f415544590000000000')
SET_SETDAT   = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
FINZ_COEFS   = bytes.fromhex('541613000846494e5a5f434f45465300000000')

def parse_resp(resp):
    if not resp:
        return "NO RESPONSE", None, None
    marker = resp[0]
    type_map = {0x52: 'SUCCESS', 0x22: 'NACK', 0x21: 'ACK'}
    mtype = type_map.get(marker, f'0x{marker:02x}')
    echoed = resp[4:14].decode('ascii', errors='replace').strip('\x00').strip() if len(resp) >= 14 else '?'
    try:
        ascii_str = resp.decode('ascii', errors='replace')
        # Split by | if present
        if '|' in ascii_str:
            parts = ascii_str.split('|')
            objs = []
            for p in parts:
                bp = p.find('{')
                if bp >= 0:
                    objs.append(json.loads(p[bp:p.rfind('}')+1]))
            return mtype, echoed, objs
        else:
            bp = ascii_str.find('{')
            be = ascii_str.rfind('}')
            if bp >= 0 and be >= 0:
                return mtype, echoed, json.loads(ascii_str[bp:be+1])
    except:
        pass
    return mtype, echoed, resp[:40].hex()

def send(sock, name, data, delay=0.05):
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
    print("✅ Connected — waiting 1 second for AVR to initialize...")
    time.sleep(1.0)  # Longer delay to let AVR settle after TCP handshake

    print("\n=== TEST 1: Exact AcoustiX bytes ===")
    
    resp = send(sock, 'GET_AVRINF', GET_AVRINF, delay=0.3)
    mtype, echoed, obj = parse_resp(resp)
    print(f"→ GET_AVRINF: {mtype} | {echoed} | {obj}")

    resp = send(sock, 'ENTER_AUDY', ENTER_AUDY1, delay=0.3)
    mtype, echoed, obj = parse_resp(resp)
    print(f"→ ENTER_AUDY: {mtype} | {echoed} | {obj}")

    resp = send(sock, 'ENTER_AUDY2', ENTER_AUDY2, delay=0.3)
    mtype, echoed, obj = parse_resp(resp)
    print(f"→ ENTER_AUDY2: {mtype} | {echoed} | {obj}")

    resp = send(sock, 'SET_SETDAT', SET_SETDAT, delay=0.3)
    mtype, echoed, obj = parse_resp(resp)
    print(f"→ SET_SETDAT: {mtype} | {echoed} | {obj}")

    print("\n=== TEST 2: Raw ASCII on port 1256 ===")
    sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock2.settimeout(15)
    sock2.connect((IP, PORT))
    time.sleep(0.5)
    sock2.send(b'GET_AVRINF\r')
    time.sleep(0.5)
    resp = b''
    try:
        while True:
            chunk = sock2.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass
    mtype, echoed, obj = parse_resp(resp)
    print(f"Raw ASCII 'GET_AVRINF\\r': {mtype} | {echoed} | {obj}")

    print("\n=== TEST 3: Zero-delay rapid fire ===")
    sock3 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock3.settimeout(15)
    sock3.connect((IP, PORT))
    time.sleep(0.5)
    # Rapid fire exact bytes like AcoustiX
    sock3.send(GET_AVRINF)
    time.sleep(0.05)
    resp1 = b''
    try:
        while True:
            chunk = sock3.recv(8192)
            if not chunk: break
            resp1 += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass
    
    sock3.send(ENTER_AUDY1)
    time.sleep(0.05)
    resp2 = b''
    try:
        while True:
            chunk = sock3.recv(8192)
            if not chunk: break
            resp2 += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass

    m1, e1, o1 = parse_resp(resp1)
    m2, e2, o2 = parse_resp(resp2)
    print(f"Rapid GET_AVRINF: {m1} | {e1} | {o1}")
    print(f"Rapid ENTER_AUDY: {m2} | {e2} | {o2}")

    sock.close()
    sock2.close()
    sock3.close()
    print("\n🛑 Done")

if __name__ == "__main__":
    main()