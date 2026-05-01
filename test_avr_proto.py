#!/usr/bin/env python3
"""
avr_proto_test.py — Test the Denon/Marantz AVR binary protocol on port 1256
Run from your Mac: python3 test_avr_proto.py [AVR_IP]

Vasu's AVR: 192.168.50.2

Message format (reverse-engineered from live AcoustiX pcap):
  T(1) + 3-byte counter + cmd_type_flag + cmd(10, space-padded) + 0x00 + meta

  cmd_type_flag:
    0x00 = query/control commands (GET_*, ENTER_*)
    0x08 = data transfer commands (SET_*, FINZ_COEFS, SET_COEFDT)

  meta:
    3 bytes for query/control (e.g. \x00\x00\x6c for GET_AVRINF)
    4 bytes for data transfer (e.g. \x02\x00\x00\x00 for SET_COEFDT)

Commands are ALWAYS 10 bytes (space-padded if shorter).
Null terminator (0x00) at position 15 after command.
Total header = 20 bytes. Data follows header.

Responses:
  0x22 = NACK
  0x21 = ACK
  After marker: 00 00 + echoed command (10 bytes) + meta + JSON
"""

import socket
import json
import sys
import time

AVR_IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256
TIMEOUT = 8

# Global message counter (increments per message)
_msg_counter = 0

def next_counter():
    global _msg_counter
    _msg_counter += 1
    return _msg_counter.to_bytes(3, 'little')

def build_msg(cmd_name, has_data=False, meta=b'\x00\x00\x00', json_data=b''):
    """
    Build a client→AVR binary message.

    cmd_type_flag: 0x00 for query/control, 0x08 for data transfer
    """
    counter = next_counter()
    cmd_bytes = cmd_name.encode('ascii').ljust(10, b' ')
    cmd_type_flag = b'\x08' if has_data else b'\x00'
    header = b'T' + counter + cmd_type_flag + cmd_bytes + b'\x00' + meta
    return header + json_data

def parse_response(data):
    """Parse AVR→client response into a readable dict."""
    if not data:
        return {"error": "no data received"}

    result = {}

    # Byte 0: 0x22=NACK, 0x21=ACK
    if data[0] == 0x22:
        result["ack"] = "NACK"
    elif data[0] == 0x21:
        result["ack"] = "ACK"
    else:
        result["ack"] = f"unknown(0x{data[0]:02x})"

    # Bytes 1-2: unknown (always 00 00 in observed responses)
    result["unknown_bytes"] = data[1:3].hex()

    # Bytes 3-12: echoed command name (10 bytes)
    echoed_cmd = data[3:13].decode('ascii', errors='replace').strip()
    result["echoed_cmd"] = echoed_cmd

    # Find JSON in the response
    try:
        ascii_str = data.decode('ascii', errors='replace')
        brace_pos = ascii_str.find('{')
        if brace_pos >= 0:
            json_str = ascii_str[brace_pos:]
            try:
                result["json"] = json.loads(json_str)
            except json.JSONDecodeError:
                result["json_partial"] = json_str[:150]
    except:
        pass

    # Show raw if no JSON found
    if "json" not in result and "json_partial" not in result:
        result["raw_hex"] = data[13:60].hex()

    return result

def send_msg(sock, msg, verbose=True):
    """Send a message and receive/parse the response."""
    cmd_name = msg[5:15].decode('ascii', errors='replace').strip()
    if verbose:
        print(f"  → {cmd_name} ({len(msg)} bytes) {msg[4:15].hex()}")

    sock.send(msg)
    time.sleep(0.2)

    # Receive response
    resp = b''
    sock.settimeout(TIMEOUT)
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b'}' in chunk:
                break
        except socket.timeout:
            break

    if verbose:
        parsed = parse_response(resp)
        print(f"  ← ACK={parsed['ack']} | cmd={parsed.get('echoed_cmd','?')} | {parsed.get('json', parsed.get('json_partial', parsed.get('raw_hex','?')))}")
        print()

    return resp

def main():
    global _msg_counter
    _msg_counter = 0

    print(f"\n🔌 Connecting to {AVR_IP}:{PORT}...\n")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        sock.connect((AVR_IP, PORT))
        print("✅ Connected!\n")
        time.sleep(0.3)

        # ── GET_AVRINF ──────────────────────────────────────────
        print("📋 GET_AVRINF — query AVR info")
        msg = build_msg('GET_AVRINF', has_data=False, meta=b'\x00\x00\x6c')
        send_msg(sock, msg)

        # ── GET_AVRSTS ──────────────────────────────────────────
        print("📋 GET_AVRSTS — query AVR status")
        msg = build_msg('GET_AVRSTS', has_data=False, meta=b'\x00\x00\x73')
        send_msg(sock, msg)

        # ── GET_COEFEX ──────────────────────────────────────────
        print("📋 GET_COEFEX — query coefficient info")
        msg = build_msg('GET_COEFEX', has_data=False, meta=b'\x00\x00\x10')
        send_msg(sock, msg)

        # ── GET_ALLCOEF ──────────────────────────────────────────
        print("📋 GET_ALLCOEF — query all coefficients info")
        msg = build_msg('GET_ALLCOEF', has_data=False, meta=b'\x00\x00\x10')
        send_msg(sock, msg)

        # ── ENTER_AUDY ──────────────────────────────────────────
        print("📋 ENTER_AUDY — enter Audyssey calibration mode")
        msg = build_msg('ENTER_AUDY', has_data=False, meta=b'\x00\x00\x00')
        send_msg(sock, msg)

        # ── SET_SETDAT: AmpAssign (has JSON data) ──────────────
        print("📋 SET_SETDAT — AmpAssign (11ch)")
        ampassign = b'{"AmpAssign":"11ch"}'
        meta = b'\x00\x00' + bytes([len(ampassign)])  # 3rd byte = JSON length
        msg = build_msg('SET_SETDAT', has_data=True, meta=meta, json_data=ampassign)
        send_msg(sock, msg)

        # ── FINZ_COEFS ──────────────────────────────────────────
        print("📋 FINZ_COEFS — apply coefficients")
        msg = build_msg('FINZ_COEFS', has_data=True, meta=b'\x00\x00\x00')
        send_msg(sock, msg)

        print("🛑 Disconnecting...")
        sock.close()
        print("✅ Done!")

    except socket.timeout:
        print("❌ Connection timed out — is the AVR reachable?")
    except ConnectionRefusedError:
        print("❌ Connection refused — is port 1256 open on the AVR?")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()