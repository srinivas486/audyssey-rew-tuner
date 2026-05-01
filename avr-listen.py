#!/usr/bin/env python3
"""
AVR connection listener — keeps connection open and captures all AVR output.
Usage: python3 avr-listen.py [192.168.50.2]
"""

import socket
import time
import sys

HOST = sys.argv[1] if len(sys.argv) > 1 else '192.168.50.2'
PORT = 23
TIMEOUT = 30  # seconds to listen

print(f"Connecting to {HOST}:{PORT}...")
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(TIMEOUT)

try:
    s.connect((HOST, PORT))
    print("Connected! Listening for up to 30s...\n")
except Exception as e:
    print(f"Connection failed: {e}")
    sys.exit(1)

buf = b''
start = time.time()
last = time.time()

while time.time() - start < TIMEOUT:
    try:
        d = s.recv(4096)
        if d:
            print(repr(d))
            last = time.time()
            buf += d
        else:
            if time.time() - last > 2:
                print("(no data for 2s, sending probe...)")
                s.sendall(b'?\r')
                last = time.time()
    except socket.timeout:
        print("(recv timeout, sending probe...)")
        try:
            s.sendall(b'?\r')
            last = time.time()
        except:
            break
    except Exception as e:
        print(f"Error: {e}")
        break

print(f"\nDone. {len(buf)} bytes collected.")
s.close()
