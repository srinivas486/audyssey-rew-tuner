#!/usr/bin/env python3
"""
avr_proto_v2.py — Test raw text vs binary approaches on port 1256
Run: python3 avr_proto_v2.py [AVR_IP]
"""
import socket, sys, time

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.2"
PORT = 1256

def hexprint(label, data):
    print(f"  {label} ({len(data)} bytes): {data.hex()}")
    ascii_str = ''.join(chr(b) if 32<=b<127 else '.' for b in data)
    print(f"  {label} ASCII: {ascii_str}")

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(8)
sock.connect((IP, PORT))
print(f"✅ Connected to {IP}:{PORT}\n")

time.sleep(0.3)

# Test 1: Raw ASCII text command (like Telnet on port 23)
print("📋 Test 1: Raw ASCII text 'GET_AVRINF\\r'")
sock.send(b'GET_AVRINF\r')
time.sleep(0.5)
resp = sock.recv(4096)
hexprint("Response", resp)

# Test 2: Binary with exact AcoustiX header format
# AcoustiX message: 54 00 13 00 00 GET_AVRINF 00 00 6c (19 bytes)
print("\n📋 Test 2: Exact AcoustiX binary format")
msg = bytes.fromhex('54001300004745545f415652494e460000006c')
sock.send(msg)
time.sleep(0.5)
resp = sock.recv(4096)
hexprint("Response", resp)

# Test 3: Exact AcoustiX GET_AVRSTS
print("\n📋 Test 3: AcoustiX GET_AVRSTS")
msg = bytes.fromhex('540a130000474554415652535453000000730000')
sock.send(msg)
time.sleep(0.5)
resp = sock.recv(4096)
hexprint("Response", resp)

# Test 4: Exact AcoustiX GET_COEFEX
print("\n📋 Test 4: AcoustiX GET_COEFEX")
msg = bytes.fromhex('5400130000474554434f4546580000001000')
sock.send(msg)
time.sleep(0.5)
resp = sock.recv(4096)
hexprint("Response", resp)

sock.close()
print("\n✅ Done")