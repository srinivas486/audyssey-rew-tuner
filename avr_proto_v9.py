#!/usr/bin/env python3
"""
avr_proto_v9.py — Critical discovery: 12-byte handshake before binary commands
This handshake (02 04 05 b4 ...) is sent before GET_AVRINF in the AVR-config-only pcap.
It might be the "device registration" that unlocks calibration commands.

Run: python3 avr_proto_v9.py [AVR_IP]
"""
import socket, sys, time, json

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256

# The 12-byte handshake (from pcap)
HANDSHAKE_CLIENT = bytes.fromhex('020405b40103030801010402')
HANDSHAKE_AVR    = bytes.fromhex('020405b40101040201030303')

# Exact AcoustiX binary commands
GET_AVRINF  = bytes.fromhex('54001300004745545f415652494e460000006c')
GET_AVRSTS  = bytes.fromhex('540a130000474554415652535453000000730000')
ENTER_AUDY1 = bytes.fromhex('5412130000454e5445525f415544590000000000')
ENTER_AUDY2 = bytes.fromhex('5413120000454e5445525f415544590000000000')
SET_SETDAT  = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
FINZ_COEFS  = bytes.fromhex('541613000846494e5a5f434f45465300000000')

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
    return mtype, echoed, {"raw_hex": resp[:40].hex()}

def send(sock, name, data, delay=0.1):
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

    # STEP 1: Send the 12-byte handshake FIRST (the missing piece!)
    print("1️⃣  Sending 12-byte handshake...")
    print(f"    → {HANDSHAKE_CLIENT.hex()}")
    sock.send(HANDSHAKE_CLIENT)
    time.sleep(0.3)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if len(resp) >= 12: break
    except socket.timeout:
        pass
    print(f"    ← {resp.hex()}")
    if resp == HANDSHAKE_AVR:
        print("    ✅ Handshake matched expected AVR response")
    else:
        print(f"    ⚠️  Unexpected response (expected {HANDSHAKE_AVR.hex()})")
    print()

    # STEP 2: GET_AVRINF (confirm connection)
    print("2️⃣  GET_AVRINF")
    resp = send(sock, 'GET_AVRINF', GET_AVRINF, delay=0.3)
    mtype, echoed, obj = parse_resp(resp)
    print(f"    {mtype} | {echoed} | {obj}")

    if isinstance(obj, dict) and obj.get('EQType'):
        print(f"    ✅ EQType={obj['EQType']} CVVer={obj['CVVer']} Ifver={obj['Ifver']}\n")

        # STEP 3: ENTER_AUDY (this should work now with handshake done)
        print("3️⃣  ENTER_AUDY (1st call)")
        resp = send(sock, 'ENTER_AUDY', ENTER_AUDY1, delay=0.3)
        mtype, echoed, obj = parse_resp(resp)
        print(f"    {mtype} | {echoed} | {obj}")

        # STEP 4: ENTER_AUDY (2nd call)
        print("4️⃣  ENTER_AUDY (2nd call)")
        resp = send(sock, 'ENTER_AUDY2', ENTER_AUDY2, delay=0.3)
        mtype, echoed, obj = parse_resp(resp)
        print(f"    {mtype} | {echoed} | {obj}")

        # STEP 5: SET_SETDAT AmpAssign
        print("5️⃣  SET_SETDAT — AmpAssign")
        resp = send(sock, 'SET_SETDAT', SET_SETDAT, delay=0.3)
        mtype, echoed, obj = parse_resp(resp)
        print(f"    {mtype} | {echoed} | {obj}")

        # STEP 6: FINZ_COEFS
        print("6️⃣  FINZ_COEFS")
        resp = send(sock, 'FINZ_COEFS', FINZ_COEFS, delay=0.3)
        mtype, echoed, obj = parse_resp(resp)
        print(f"    {mtype} | {echoed} | {obj}")
    else:
        print("    ⚠️  GET_AVRINF didn't return expected info. Skipping config commands.")

    sock.close()
    print("\n🛑 Done")

if __name__ == "__main__":
    main()