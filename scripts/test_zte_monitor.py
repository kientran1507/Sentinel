#!/usr/bin/env python3
"""Diagnostic script to run the ZTE Continuous Monitor with env credentials."""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time
from datetime import datetime

# Add repo root to import path
repo_root = pathlib.Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from scripts.test_zte_h3601p import load_dotenv
from services.discovery.zte_h3601p_client import ZTEH3601PClient, _sanitize_log_message
from services.discovery.zte_collector import ZTECollector
from services.discovery.device_registry import DeviceRegistry
from services.discovery.presence_tracker import PresenceTracker
from services.discovery.zte_monitor import ZTEMonitor


def print_event(e):
    print(f"  {e.event_type}")
    print(f"    MAC: {e.mac_address}")
    if e.device:
        print(f"    IP: {e.device.ip_address or 'N/A'}")
        print(f"    Hostname: {e.device.hostname or 'N/A'}")
        if e.device.connection_type:
            print(f"    Connection: {e.device.connection_type}")
        if e.device.interface:
            print(f"    Interface: {e.device.interface}")
    if e.previous_state and e.current_state:
        # Show what changed explicitly
        diffs = []
        for key in ("ip_address", "hostname", "connection_type"):
            prev_val = e.previous_state.get(key)
            curr_val = e.current_state.get(key)
            if prev_val != curr_val:
                diffs.append(f"{key}: {prev_val} -> {curr_val}")
        if diffs:
            print(f"    Changes: {', '.join(diffs)}")


def main():
    parser = argparse.ArgumentParser(description="Sentinel ZTE Continuous Monitor Diagnostic")
    parser.add_argument("--interval", type=float, default=10.0, help="Polling interval in seconds (default: 10)")
    parser.add_argument("--offline-threshold", type=int, default=3, help="Offline threshold (default: 3)")
    args = parser.parse_args()

    load_dotenv()
    url = os.getenv("ZTE_ROUTER_URL")
    username = os.getenv("ZTE_USERNAME")
    password = os.getenv("ZTE_PASSWORD")
    rsa_pubkey = os.getenv("ZTE_RSA_PUBLIC_KEY")

    if not url:
        print("[ERROR] ZTE_ROUTER_URL is required. Define it in .env or system environment.")
        sys.exit(1)
    if not username or not password:
        print("[ERROR] ZTE_USERNAME and ZTE_PASSWORD are required. Define them in .env.")
        sys.exit(1)

    print("==================================================")
    print(" Sentinel ZTE Continuous Monitor")
    print("==================================================")
    print()
    print("Router:")
    print(f"    {url}")
    print()
    print("Poll interval:")
    print(f"    {args.interval} seconds")
    print()
    print("Offline threshold:")
    print(f"    {args.offline_threshold} successful polls")
    print()
    print("--------------------------------------------------")
    print()

    # Instantiate the client
    client = ZTEH3601PClient(
        url=url,
        username=username,
        password=password,
        verify_tls=False,
        password_algorithm="sha256_concat",
        rsa_public_key=rsa_pubkey,
    )

    # Setup monitor stack
    collector = ZTECollector(client)
    registry = DeviceRegistry()
    tracker = PresenceTracker(registry, offline_threshold=args.offline_threshold)

    monitor = ZTEMonitor(
        client=client,
        poll_interval=args.interval,
        offline_threshold=args.offline_threshold,
        collector=collector,
        registry=registry,
        presence_tracker=tracker,
    )

    print("[BASELINE]")
    try:
        baseline_events = monitor.poll_once()
        devices = registry.get_all()
        print(f"Devices discovered: {len(devices)}")
        # Print a short list of discovered devices
        for d in devices[:5]:
            print(f"  - MAC: {d.mac_address} ({d.ip_address or 'No IP'}, {d.hostname or 'No Name'})")
        if len(devices) > 5:
            print(f"  ... and {len(devices) - 5} more.")
        print()
    except Exception as exc:
        print(f"[ERROR] Baseline poll failed: {_sanitize_log_message(str(exc))}")
        sys.exit(1)

    print("Starting background loop. Press Ctrl+C to terminate cleanly.")
    print("--------------------------------------------------")
    print()

    # Intercept poll_once to format CLI output
    original_poll_once = monitor.poll_once

    def diagnostic_poll_once():
        time_str = datetime.now().strftime("%H:%M:%S")
        events = original_poll_once()
        online_count = len([d for d in registry.get_all() if d.status == "online"])
        
        print(f"[{time_str}] Poll successful")
        print(f"Devices online: {online_count}")
        print(f"Events: {len(events)}")
        for e in events:
            print_event(e)
        print()
        return events

    monitor.poll_once = diagnostic_poll_once

    # Start the monitor in background thread
    monitor.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping monitor cleanly...")
        monitor.stop()
        print("Goodbye!")


if __name__ == "__main__":
    main()
