"""Prepare and check the Docker-free local browser; never starts model calls."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from validation.native import BROWSERS, environment_identity

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "check"])
    args = parser.parse_args()
    if args.action == "prepare":
        BROWSERS.mkdir(parents=True, mode=0o700, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"],
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(BROWSERS)}, check=True,
        )
    try:
        print("Native OS sandbox and Chromium: OK\n" + environment_identity())
    except (OSError, ValueError, ImportError, subprocess.SubprocessError) as exc:
        print(f"Native validator is unavailable: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
