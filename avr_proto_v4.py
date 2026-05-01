#!/usr/bin/env python3
"""
avr_proto_v4.py — Try alternative sequences to unlock AVR calibration mode

Observations so far:
- GET_AVRINF works perfectly → returns full AVR info with "MultEQXT32"
- All config commands (ENTER_AUDY, SET_SETDAT, FINZ_COEFS) return NACK
- Counter must start at 0x1313 (AcoustiX style) for AVR to respond
- Response format: 0x52 marker + [2-byte counter] + [echoed cmd, 8 chars? padded] + meta + JSON

Key hypothesis: The AVR needs to be in a specific state (power on, HDMI active,
or a specific calibration phase) before it accepts config commands.
"""
import socket, sys, time, struct, json

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256
_counter = 0x1313

def build_msg(cmd_name, has_data=False, meta=b'\x00\x00\x00', json_data=b''):
    global _counter
    _counter += 1
    counter = _counter.to_bytes(3, 'little')
    cmd_bytes = cmd_name.encode('ascii').ljust(10, b' ')
    cmd_flag = b'\x08' if has_data else b'\x00'
    header = b'T' + counter + cmd_flag + cmd_bytes + b'\x00' + meta
    return header + json_data

def send(sock, msg, label=""):
    cmd_name = msg[5:15].decode('ascii', errors='replace').strip()
    print(f"  → {label or cmd_name} ({len(msg)}b) {msg.hex()}")
    sock.send(msg)
    time.sleep(0.4)
    resp = b''
    sock.settimeout(10)
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass

    if not resp:
        print(f"  ← (no response)")
        return None

    # Parse response
    marker = resp[0]
    type_map = {0x52: 'SUCCESS', 0x22: 'NACK', 0x21: 'ACK'}
    print(f"  ← marker=0x{marker:02x}({type_map.get(marker,'?')}) ", end='')

    # Echoed command: bytes 3-10 (8 bytes, space-padded)
    if len(resp) >= 11:
        echo = resp[3:11].decode('ascii', errors='replace').strip()
        print(f"echo={echo!r} ", end='')

    # JSON — find first { and last }
    try:
        ascii_str = resp.decode('ascii', errors='replace')
        # The JSON part comes after the last '}' before the '|' separator
        # Format: {info_json} | {comm_json}
        pipe_pos = ascii_str.rfind('|')
        if pipe_pos >= 0:
            json_str = ascii_str[ascii_str.rfind('{', 0, pipe_pos):pipe_pos]
        else:
            brace_pos = ascii_str.find('{')
            brace_end = ascii_str.rfind('}')
            if brace_end >= 0:
                json_str = ascii_str[brace_pos:brace_end+1]
            else:
                json_str = ascii_str[ascii_str.find('{'):]
        obj = json.loads(json_str)
        print(f"JSON={obj}")
        return obj
    except Exception as e:
        print(f"parse_err={e} raw={resp[:40].hex()}")
        return None

def main():
    global _counter
    _counter = 0x1313

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((IP, PORT))
    print(f"✅ Connected to {IP}:{PORT}\n")
    time.sleep(0.3)

    # 1. Confirm AVR is alive
    print("1️⃣  GET_AVRINF")
    r = send(sock, build_msg('GET_AVRINF', has_data=False, meta=b'\x00\x00\x6c'))
    if r and r.get('EQType'):
        print(f"   ✅ EQType={r['EQType']} CVVer={r['CVVer']} Ifver={r['Ifver']}\n")
    else:
        print("   ⚠️  AVR not responding as expected — try power cycling the AVR")
        return

    # 2. GET_COEFEX — coefficient export/import info
    print("2️⃣  GET_COEFEX")
    send(sock, build_msg('GET_COEFEX', has_data=False, meta=b'\x00\x00\x10'))

    # 3. GET_ALLCOEF — get ALL coefficient data
    print("3️⃣  GET_ALLCOEF")
    send(sock, build_msg('GET_ALLCOEF', has_data=False, meta=b'\x00\x00\x10'))

    # 4. GET_REMOTYP — remote type (maybe need to identify as a valid controller)
    print("4️⃣  GET_REMOTYP")
    send(sock, build_msg('GET_REMOTYP', has_data=False, meta=b'\x00\x00\x10'))

    # 5. ENTER_AUDY — enter Audyssey mode
    print("5️⃣  ENTER_AUDY")
    send(sock, build_msg('ENTER_AUDY', has_data=False, meta=b'\x00\x00\x00'))

    # 6. Try sending ENTER_AUDY twice in a row
    print("6️⃣  ENTER_AUDY (2nd call)")
    send(sock, build_msg('ENTER_AUDY', has_data=False, meta=b'\x00\x00\x00'))

    # 7. Try SETCONFIG — some kind of configuration
    print("7️⃣  SETCONFIG")
    send(sock, build_msg('SETCONFIG', has_data=True, meta=b'\x00\x00\x00'))

    # 8. Try raw text on port 1256 (like port 23)
    print("8️⃣  Raw ASCII 'GET_COEFEX\\r' on port 1256")
    sock.send(b'GET_COEFEX\r')
    time.sleep(0.4)
    resp = b''
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk: break
            resp += chunk
            if b'}' in chunk: break
    except socket.timeout:
        pass
    if resp:
        print(f"  ← raw response: {resp[:80].hex()}")
        try:
            ascii_str = resp.decode('ascii', errors='replace')
            print(f"  ← {ascii_str}")
        except:
            pass
    else:
        print(f"  ← (no response)")

    sock.close()
    print("\n🛑 Done")

if __name__ == "__main__":
    main()
