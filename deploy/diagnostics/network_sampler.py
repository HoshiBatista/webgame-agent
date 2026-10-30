#!/usr/bin/python3
"""Passive VPS-only counters. Does not connect to/ping/probe any remote server."""

import argparse
import json
import logging
import logging.handlers
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def command(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=4)
        return result.stdout.strip() if result.returncode == 0 else {"exit_code": result.returncode}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error_type": type(exc).__name__}


def counters(interface):
    result = {}
    for key in ("rx_bytes", "tx_bytes", "rx_errors", "tx_errors", "rx_dropped", "tx_dropped"):
        try:
            result[key] = int(Path(f"/sys/class/net/{interface}/statistics/{key}").read_text())
        except (OSError, ValueError):
            result[key] = None
    return result


def sample():
    handshakes = command("wg", "show", "wg-llm", "latest-handshakes")
    if isinstance(handshakes, str):
        # Public/private VPN keys and endpoint details are deliberately excluded.
        handshakes = [int(row.split()[1]) for row in handshakes.splitlines() if len(row.split()) == 2]
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.split(":")[0] in {"MemAvailable", "MemTotal", "SwapFree"}:
            mem[line.split(":")[0]] = int(line.split()[1])
    return {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "wg_handshake_unix": handshakes, "wg_counters": counters("wg-llm"),
        "sockets": command("ss", "-tinHO", "( sport = :443 or ( dst 172.22.222.8 and dport = :8000 ) )"),
        "memory_kib": mem, "load": os.getloadavg(),
        "caddy": command("systemctl", "show", "caddy", "-p", "MainPID", "-p", "NRestarts",
                         "-p", "ExecMainStartTimestampMonotonic", "-p", "MemoryCurrent"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        print(json.dumps(sample()))
        return
    os.umask(0o077)
    logger = logging.getLogger("llm-network")
    logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        "/var/log/llm-diagnostics/network.jsonl", maxBytes=2 * 1024 * 1024, backupCount=9
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    while True:
        try:
            logger.info(json.dumps(sample()))
        except Exception as exc:
            logger.info(json.dumps({"ts": datetime.now(UTC).isoformat(), "error_type": type(exc).__name__}))
        time.sleep(10)


if __name__ == "__main__":
    main()
