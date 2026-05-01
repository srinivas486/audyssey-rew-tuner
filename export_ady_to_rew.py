#!/usr/bin/env python3
"""End-to-end pipeline: load an ADY file, export .frd files, and push to REW.

Usage::

    python export_ady_to_rew.py <path-to.ady> [--output-dir ./output]
                                     [--api-host localhost]
                                     [--api-port 4735]
                                     [--export]        write .frd files to --output-dir
                                     [--no-push]       skip REW API push
                                     [--ir]            include impulse response data (default: frequency response only)

Examples::

    python export_ady_to_rew.py test.ady                 # push IR to REW (default)
    python export_ady_to_rew.py test.ady --export        # also write .frd files to --output-dir
    python export_ady_to_rew.py test.ady --no-push --export  # export .frd only (no REW push)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ady_parser import load_ady, get_all_channels_freq_response, get_all_channels_ir
from rew_exporter import (
    export_channel_frd,
    push_frequency_response_via_api,
    push_impulse_response_via_api,
    clear_measurements_via_api,
)
from target_curve import (
    generate_house_curve,
    export_merged_target,
    push_merged_target_via_api,
    TargetCurveParams,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export ADY frequency response data to REW .frd files and/or REW API."
    )
    parser.add_argument("ady_path", help="Path to the .ady measurement file")
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory to write .frd files into (default: ./output)",
    )
    parser.add_argument(
        "--api-host",
        default="localhost",
        help="REW API host (default: localhost)",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=4735,
        help="REW API port (default: 4735)",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        default=False,
        help="Also write .frd files to --output-dir (disabled by default; REW API push is default)",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Skip pushing to REW API",
    )
    parser.add_argument(
        "--ir",
        action="store_true",
        help="Push impulse response data instead of frequency response "
             "(enables RT60, group delay, impulse, spectrogram views in REW)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete all existing measurements in REW before importing",
    )
    parser.add_argument(
        "--target-curve",
        action="store_true",
        default=False,
        help="Generate a house curve from speaker + subwoofer measurements and load it into REW",
    )
    parser.add_argument(
        "--target-spl",
        type=float,
        default=None,
        help="Target SPL in dB for the house curve midrange (e.g. 85). "
             "If not set, inferred from measurement reference levels.",
    )
    args = parser.parse_args()

    ady_path = Path(args.ady_path)
    if not ady_path.exists():
        sys.stderr.write(f"Error: file not found: {ady_path}\n")
        sys.exit(1)

    # --- Clear REW measurements first (--clear flag) ---
    if args.clear and not args.no_push:
        print("Clearing all existing REW measurements...")
        clear_measurements_via_api(host=args.api_host, port=args.api_port)

    print(f"Loading ADY file: {ady_path}")
    try:
        data = load_ady(str(ady_path))
    except Exception as e:
        sys.stderr.write(f"Error loading ADY file: {e}\n")
        sys.exit(1)

    # --- Impulse response mode ---
    if args.ir:
        print("Extracting impulse responses...")
        channel_irs = get_all_channels_ir(data)
        print(f"  {len(channel_irs)} channel(s) processed")

        ir_ok = True
        for ch_ir in channel_irs:
            cmd_id = ch_ir["commandId"]
            samples = ch_ir["samples"]
            sample_rate = ch_ir["sample_rate"]

            if not args.no_push:
                ok = push_impulse_response_via_api(
                    samples,
                    cmd_id,
                    sample_rate=sample_rate,
                    host=args.api_host,
                    port=args.api_port,
                )
                status = "✓" if ok else "✗"
                print(f"  [{status}] IR push: {cmd_id} ({ch_ir['n_samples']} samples)")
                if not ok:
                    ir_ok = False

        if not args.no_push:
            print()
            print(f"REW IR push: {'PASS' if ir_ok else 'FAIL'}")
        return

    # --- Target curve mode ---
    if args.target_curve:
        print("Generating house curve from speaker + subwoofer measurements...")
        channel_responses = get_all_channels_freq_response(data)
        params = TargetCurveParams()
        if args.target_spl is not None:
            params.target_spl_db = args.target_spl

        freqs, house_spl = generate_house_curve(channel_responses, params)

        if len(freqs) == 0:
            sys.stderr.write("No speaker or subwoofer channels found.\n")
            sys.exit(1)

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Writing house curve ({len(freqs)} points)...")
        ok = export_merged_target(freqs, house_spl, output_dir)
        if not ok:
            sys.stderr.write("Failed to write house curve file.\n")
            sys.exit(1)

        if not args.no_push:
            print(f"Pushing house curve to REW at {args.api_host}:{args.api_port}...")
            pushed = push_merged_target_via_api(
                freqs, house_spl,
                host=args.api_host,
                port=args.api_port,
            )
            if pushed:
                print("House curve loaded into REW ✓")
            else:
                sys.stderr.write("Failed to push house curve to REW.\n")
                sys.exit(1)
        print(f"House curve: {output_dir / 'merged_target.frd'}")
        return

    # --- Frequency response mode (default) ---
    print("Computing frequency responses...")
    channel_responses = get_all_channels_freq_response(data)
    print(f"  {len(channel_responses)} channel(s) processed")

    frd_ok = True
    api_ok = True

    for ch in channel_responses:
        cmd_id = ch["commandId"]
        avg = ch["averaged"]
        freq = list(avg["freq_hz"])   # np.ndarray → plain list
        spl = list(avg["spl_db"])      # np.ndarray → plain list

        # --- .frd export ---
        if args.export:
            ok = export_channel_frd(freq, spl, args.output_dir, cmd_id)
            status = "✓" if ok else "✗"
            print(f"  [{status}] .frd export: {cmd_id}")
            if not ok:
                frd_ok = False

        # --- REW API push ---
        if not args.no_push:
            ok = push_frequency_response_via_api(
                freq, spl, cmd_id,
                host=args.api_host,
                port=args.api_port,
            )
            status = "✓" if ok else "✗"
            print(f"  [{status}] REW API push: {cmd_id}")
            if not ok:
                api_ok = False

    # Summary
    print()
    if args.export:
        print(f".frd export: {'PASS' if frd_ok else 'FAIL'}")
    if not args.no_push:
        push_status = 'PASS' if api_ok else 'FAIL'
        print(f"REW API push: {push_status}")


if __name__ == "__main__":
    main()
