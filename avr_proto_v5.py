#!/usr/bin/env python3
"""
avr_proto_v5.py — Critical protocol fix: response format is echoed command as 8 bytes, not 10.
Also: meta is 3 bytes for queries, 4 bytes for data transfer.
Run: python3 avr_proto_v5.py [AVR_IP]
"""
import socket, sys, time, struct, json

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256
_counter = 0x1313

def build_msg(cmd_name, has_data=False, meta=None):
    """Build AVR binary message. meta defaults to 3 null bytes for query, 4 for data."""
    global _counter
    _counter += 1
    counter = _counter.to_bytes(3, 'little')
    cmd_bytes = cmd_name.encode('ascii').ljust(10, b' ')
    cmd_flag = b'\x08' if has_data else b'\x00'
    if meta is None:
        meta = b'\x00\x00\x00\x00' if has_data else b'\x00\x00\x00'
    header = b'T' + counter + cmd_flag + cmd_bytes + b'\x00' + meta
    return header

def parse_resp(resp):
    """Parse AVR response, return (type, echoed_cmd, json_obj)."""
    if not resp:
        return None, None, None
    marker = resp[0]
    type_map = {0x52: 'SUCCESS', 0x22: 'NACK', 0x21: 'ACK'}
    mtype = type_map.get(marker, f'unknown(0x{marker:02x})')

    # Echoed command: bytes 4-11 (8 bytes) — confirmed from NACK responses
    echoed = resp[4:12].decode('ascii', errors='replace').strip()

    # JSON starts at byte 17 (after marker + len + null + 8-byte-cmd + null + 3 meta)
    # But for success responses with 4-byte meta, JSON starts at byte 18
    json_start = 17  # default for NACK (3-byte meta)
    json_str = None
    try:
        ascii_str = resp.decode('ascii', errors='replace')
        brace_pos = ascii_str.find('{')
        brace_end = ascii_str.rfind('}')
        if brace_pos >= 0 and brace_end >= 0:
            json_str = ascii_str[brace_pos:brace_end+1]
            obj = json.loads(json_str)
            return mtype, echoed, obj
    except:
        pass

    return mtype, echoed, json_str

def send_msg(sock, msg, label=""):
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

    mtype, echoed, obj = parse_resp(resp)
    if isinstance(obj, dict):
        print(f"  ← {mtype} | echo={echoed!r} | {obj}")
    else:
        print(f"  ← {mtype} | echo={echoed!r} | raw={resp[:40].hex()}")
    print()
    return mtype, echoed, obj

def main():
    global _counter
    _counter = 0x1313

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((IP, PORT))
    print(f"✅ Connected to {IP}:{PORT}\n")
    time.sleep(0.3)

    # Step 1: GET_AVRINF — confirm AVR is alive
    print("1️⃣  GET_AVRINF")
    r_type, r_echo, r_obj = send_msg(sock, build_msg('GET_AVRINF', has_data=False, meta=b'\x00\x00\x6c'))

    if r_type == 'SUCCESS' and r_obj and r_obj.get('EQType'):
        print(f"   ✅ EQType={r_obj['EQType']} CVVer={r_obj['CVVer']} Ifver={r_obj['Ifver']}")
        print(f"   ADC={r_obj.get('ADC')} SysDelay={r_obj.get('SysDelay')} SWLvlMatch={r_obj.get('SWLvlMatch')}\n")

        # Step 2: GET_COEFEX — coefficient info
        print("2️⃣  GET_COEFEX")
        send_msg(sock, build_msg('GET_COEFEX', has_data=False, meta=b'\x00\x00\x10'))

        # Step 3: GET_ALLCOEF — get ALL coefficient data
        print("3️⃣  GET_ALLCOEF")
        send_msg(sock, build_msg('GET_ALLCOEF', has_data=False, meta=b'\x00\x00\x10'))

        # Step 4: Try ENTER_AUDY with different meta values
        print("4️⃣  ENTER_AUDY (meta=000000)")
        send_msg(sock, build_msg('ENTER_AUDY', has_data=False, meta=b'\x00\x00\x00'))

        print("4b️  ENTER_AUDY (meta=000001)")
        send_msg(sock, build_msg('ENTER_AUDY', has_data=False, meta=b'\x00\x00\x01'))

        # Step 5: Try raw text on port 1256
        print("5️⃣  Raw text: 'GET_COEFEX\\r'")
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
            print(f"  ← {resp[:60].hex()}")
            try:
                ascii_str = resp.decode('ascii', errors='replace')
                obj = json.loads(ascii_str[ascii_str.find('{'):ascii_str.rfind('}')+1])
                print(f"  ← {obj}")
            except:
                pass
        print()

    else:
        print("   ⚠️  AVR not responding as expected. Try power cycling the AVR.")
        return

    sock.close()
    print("🛑 Done")

if __name__ == "__main__":
    main()