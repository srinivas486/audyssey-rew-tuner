#!/usr/bin/env python3
"""
avr_proto_v6.py — Send EXACT AcoustiX bytes, compare responses byte-by-byte
Run: python3 avr_proto_v6.py [AVR_IP]
"""
import socket, sys, time, json

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256

# Exact AcoustiX bytes (extracted from pcap)
ACCEPTED_COMMANDS = {
    'GET_AVRINF': bytes.fromhex('54001300004745545f415652494e460000006c'),
    'GET_AVRSTS': bytes.fromhex('540a130000474554415652535453000000730000'),
    'ENTER_AUDY': bytes.fromhex('5412130000454e5445525f415544590000000000'),
    'SET_SETDAT_AMP': bytes.fromhex('54002700005345545f5345544441540000147b22416d7041737369676e223a2231316368227d09'),
    'SET_SETDAT_FIN': bytes.fromhex('54002700005345545f5345544441540000137b224164797466696e666c673a46696e227d'),
}

def send_exact(sock, name, data):
    print(f"\n  → {name} ({len(data)} bytes)")
    print(f"    hex: {data.hex()}")
    sock.send(data)
    time.sleep(0.4)

    resp = b''
    sock.settimeout(10)
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk and b'|' in chunk: break
            if b'}' in chunk: break
    except socket.timeout:
        pass

    if resp:
        print(f"    ← ({len(resp)} bytes) {resp[:60].hex()}")
        # Parse response
        marker = resp[0]
        type_map = {0x52: 'SUCCESS', 0x22: 'NACK', 0x21: 'ACK'}
        print(f"      marker=0x{marker:02x}({type_map.get(marker,'?')})")

        # Echoed command: bytes 4-11 (8 bytes)
        if len(resp) >= 12:
            echo = resp[4:12].decode('ascii', errors='replace').strip('\x00').strip()
            print(f"      echoed_cmd={echo!r}")

        # JSON
        try:
            ascii_str = resp.decode('ascii', errors='replace')
            # Split by | if present (some responses have two JSON objects)
            if '|' in ascii_str:
                parts = ascii_str.split('|')
                for i, part in enumerate(parts):
                    brace_pos = part.find('{')
                    if brace_pos >= 0:
                        obj = json.loads(part[brace_pos:])
                        print(f"      JSON[{i}]: {obj}")
            else:
                brace_pos = ascii_str.find('{')
                brace_end = ascii_str.rfind('}')
                if brace_pos >= 0 and brace_end >= 0:
                    obj = json.loads(ascii_str[brace_pos:brace_end+1])
                    print(f"      JSON: {obj}")
        except Exception as e:
            print(f"      JSON parse error: {e}")
    else:
        print(f"    ← (no response)")
    return resp

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((IP, PORT))
    print(f"✅ Connected to {IP}:{PORT}")
    time.sleep(0.3)

    # Step 1: GET_AVRINF (confirmed working in AcoustiX pcap)
    print("\n1️⃣  GET_AVRINF — verify AVR connection")
    send_exact(sock, 'GET_AVRINF', ACCEPTED_COMMANDS['GET_AVRINF'])

    # Step 2: ENTER_AUDY (sent twice in AcoustiX flow)
    print("\n2️⃣  ENTER_AUDY (1st call)")
    send_exact(sock, 'ENTER_AUDY', ACCEPTED_COMMANDS['ENTER_AUDY'])

    print("\n3️⃣  ENTER_AUDY (2nd call)")
    send_exact(sock, 'ENTER_AUDY_2nd', ACCEPTED_COMMANDS['ENTER_AUDY'])

    # Step 3: SET_SETDAT AmpAssign
    print("\n4️⃣  SET_SETDAT — AmpAssign")
    send_exact(sock, 'SET_SETDAT_AMP', ACCEPTED_COMMANDS['SET_SETDAT_AMP'])

    # Step 4: SET_SETDAT AudyFinFlg
    print("\n5️⃣  SET_SETDAT — AudyFinFlg")
    send_exact(sock, 'SET_SETDAT_FIN', ACCEPTED_COMMANDS['SET_SETDAT_FIN'])

    # Step 5: FINZ_COEFS (trigger coefficient transfer from AVR side)
    print("\n6️⃣  FINZ_COEFS — finalize")
    finz = bytes.fromhex('541613000846494e5a5f434f45465300000000')
    send_exact(sock, 'FINZ_COEFS', finz)

    sock.close()
    print("\n🛑 Done")

if __name__ == "__main__":
    main()