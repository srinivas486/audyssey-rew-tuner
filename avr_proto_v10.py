#!/usr/bin/env python3
"""
avr_proto_v10.py — Fixed JSON parsing, and test: does the 12-byte handshake
actually matter for calibration commands?

Key fixes:
- JSON parsing handles list responses (parse_resp returns [obj] not obj)
- Tests calibration commands WITHOUT the 12-byte handshake first
- Then tests WITH the 12-byte handshake to compare

Run: python3 avr_proto_v10.py [AVR_IP]
"""
import socket, sys, time, json

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256

# The 12-byte handshake
HANDSHAKE_CLIENT = bytes.fromhex('020405b40103030801010402')
HANDSHAKE_AVR    = bytes.fromhex('020405b40101040201030303')

# Exact AcoustiX commands
GET_AVRINF  = bytes.fromhex('54001300004745545f415652494e460000006c')
GET_AVRSTS  = bytes.fromhex('540a130000474554415652535453000000730000')
ENTER_AUDY1 = bytes.fromhex('5412130000454e5445525f415544590000000000')
ENTER_AUDY2 = bytes.fromhex('5413120000454e5445525f415544590000000000')
SET_SETDAT  = bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09')
FINZ_COEFS  = bytes.fromhex('541613000846494e5a5f434f45465300000000')

def parse_resp(resp):
    """Parse AVR response. Returns (type, echoed_cmd, obj_or_list)."""
    if not resp:
        return "NO RESPONSE", None, None
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
                parsed = json.loads(ascii_str[bp:be+1])
                return mtype, echoed, parsed
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

def try_handshake(sock):
    """Try the 12-byte handshake. Returns True if AVR responds correctly."""
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
    return resp == HANDSHAKE_AVR, resp

def main():
    print(f"Connecting to {IP}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)
    sock.connect((IP, PORT))
    print("✅ Connected\n")

    # STEP 1: Get AVR info
    print("1️⃣  GET_AVRINF")
    resp = send(sock, 'GET_AVRINF', GET_AVRINF, delay=0.3)
    mtype, echoed, result = parse_resp(resp)

    # Handle both dict and list responses
    info = None
    if isinstance(result, list) and len(result) > 0:
        info = result[0]
    elif isinstance(result, dict):
        info = result

    if info and info.get('EQType'):
        print(f"    {mtype} | {echoed}")
        print(f"    ✅ EQType={info['EQType']} CVVer={info['CVVer']} Ifver={info['Ifver']}")
        print()
    else:
        print(f"    {mtype} | {echoed} | {result}")
        print("    ⚠️  Could not get EQType info. Aborting.")
        sock.close()
        return

    # STEP 2: Test calibration commands WITHOUT handshake
    print("2️⃣  Testing calibration commands WITHOUT 12-byte handshake:\n")

    print("   2a️⃣  ENTER_AUDY (1st)")
    resp = send(sock, 'ENTER_AUDY1', ENTER_AUDY1, delay=0.3)
    mtype, echoed, result = parse_resp(resp)
    comm = None
    if isinstance(result, list) and len(result) > 0:
        comm = result[0].get('Comm')
    elif isinstance(result, dict):
        comm = result.get('Comm')
    print(f"       {mtype} | {echoed} | Comm={comm}")

    print("   2b️⃣  ENTER_AUDY (2nd)")
    resp = send(sock, 'ENTER_AUDY2', ENTER_AUDY2, delay=0.3)
    mtype, echoed, result = parse_resp(resp)
    if isinstance(result, list) and len(result) > 0:
        comm = result[0].get('Comm')
    elif isinstance(result, dict):
        comm = result.get('Comm')
    print(f"       {mtype} | {echoed} | Comm={comm}")

    print("   2c️⃣  SET_SETDAT (AmpAssign)")
    resp = send(sock, 'SET_SETDAT', SET_SETDAT, delay=0.3)
    mtype, echoed, result = parse_resp(resp)
    if isinstance(result, list) and len(result) > 0:
        comm = result[0].get('Comm')
    elif isinstance(result, dict):
        comm = result.get('Comm')
    print(f"       {mtype} | {echoed} | Comm={comm}")

    # STEP 3: Now try WITH handshake on a FRESH connection
    print("\n3️⃣  Testing WITH 12-byte handshake on fresh connection:\n")

    sock.close()
    sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock2.settimeout(15)
    sock2.connect((IP, PORT))
    print("   🔌 New connection established")

    # Try handshake
    ok, resp = try_handshake(sock2)
    if ok:
        print(f"   ✅ 12-byte handshake matched!")
    else:
        print(f"   ⚠️  Handshake unexpected: {resp.hex()}")
        # The AVR might just ignore it and return a binary response instead
        # Let's see what marker we got
        if resp and resp[0] == 0x52:
            print(f"      AVR responded with binary protocol instead (marker=0x52)")
        elif resp and resp[0] == 0x22:
            print(f"      AVR responded with NACK (marker=0x22)")
        else:
            print(f"      Unknown response")

    # GET_AVRINF to confirm connection
    print("\n   3a️⃣  GET_AVRINF (after handshake attempt)")
    resp = send(sock2, 'GET_AVRINF', GET_AVRINF, delay=0.3)
    mtype, echoed, result = parse_resp(resp)
    if isinstance(result, list) and len(result) > 0:
        info = result[0]
    elif isinstance(result, dict):
        info = result
    else:
        info = None
    if info and info.get('EQType'):
        print(f"       {mtype} | {echoed} | EQType={info['EQType']}")
    else:
        print(f"       {mtype} | {echoed} | {result}")

    print("   3b️⃣  ENTER_AUDY (1st)")
    resp = send(sock2, 'ENTER_AUDY1', ENTER_AUDY1, delay=0.3)
    mtype, echoed, result = parse_resp(resp)
    if isinstance(result, list) and len(result) > 0:
        comm = result[0].get('Comm')
    elif isinstance(result, dict):
        comm = result.get('Comm')
    else:
        comm = None
    print(f"       {mtype} | {echoed} | Comm={comm}")

    print("   3c️⃣  ENTER_AUDY (2nd)")
    resp = send(sock2, 'ENTER_AUDY2', ENTER_AUDY2, delay=0.3)
    mtype, echoed, result = parse_resp(resp)
    if isinstance(result, list) and len(result) > 0:
        comm = result[0].get('Comm')
    elif isinstance(result, dict):
        comm = result.get('Comm')
    else:
        comm = None
    print(f"       {mtype} | {echoed} | Comm={comm}")

    print("   3d️⃣  SET_SETDAT (AmpAssign)")
    resp = send(sock2, 'SET_SETDAT', SET_SETDAT, delay=0.3)
    mtype, echoed, result = parse_resp(resp)
    if isinstance(result, list) and len(result) > 0:
        comm = result[0].get('Comm')
    elif isinstance(result, dict):
        comm = result.get('Comm')
    else:
        comm = None
    print(f"       {mtype} | {echoed} | Comm={comm}")

    sock.close()
    sock2.close()
    print("\n🛑 Done")

if __name__ == "__main__":
    main()