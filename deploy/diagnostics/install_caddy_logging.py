#!/usr/bin/python3
"""Add access diagnostics to the existing VPS template, preserving token authorization."""

import fcntl
import json
import os
import pwd
import runpy
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def main():
    os.umask(0o077)
    base = Path("/etc/llm-proxy")
    template = base / "Caddyfile.template"
    marker = "# GAMEFORGE_DIAGNOSTICS_V1"
    with (base / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = template.read_text()
        if marker in previous:
            print("Diagnostics already installed")
            return
        sockets = subprocess.run(
            ["ss", "-Htn", "state", "established", "( dst 172.22.222.8 and dport = :8000 )"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if sockets:
            raise SystemExit("Active upstream connection: wait before reloading Caddy")
        anchor = "https://129.101.114.59 {\n"
        if previous.count(anchor) != 1 or previous.count("@@AUTH_MATCHER@@") != 1:
            raise SystemExit("Unexpected proxy template; manual review required")
        state = json.loads((base / "tokens.json").read_text())
        tokens = [record["token"] for _, record in sorted(state.items())]
        matcher = "\n".join(["@unauthorized {", "    not {"] + [
            "        header Authorization " + json.dumps("Bearer " + token) for token in tokens
        ] + ["    }", "}"]) if tokens else "@unauthorized path *"
        expected = previous.replace("@@AUTH_MATCHER@@", matcher).replace(
            "@@UPSTREAM_AUTH@@", json.dumps("Bearer " + (base / "upstream.key").read_text().strip())
        )
        if Path("/etc/caddy/Caddyfile").read_text() != expected:
            raise SystemExit("Live Caddyfile differs from template; review drift before deployment")
        fragment = Path(__file__).with_name("caddy-site.fragment").read_text()
        updated = previous.replace(anchor, anchor + fragment + "\n", 1)
        # These fixed labels identify routes without recording user-controlled URLs/queries.
        for name in ("models", "generate", "proxy_health"):
            needle = f"handle @{name} {{\n"
            if updated.count(needle) != 1:
                raise SystemExit("Unexpected proxy routes; manual review required")
            updated = updated.replace(needle, needle + f"            log_append endpoint {name}\n", 1)
        backup = base / ("Caddyfile.template.before-diagnostics-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
        backup.write_text(previous)
        # Root's validation opens file writers too; pre-create with the runtime owner's permissions.
        caddy_user = pwd.getpwnam("caddy")
        log = Path("/var/log/caddy/llm-access.jsonl")
        log.touch(exist_ok=True)
        os.chown(log, caddy_user.pw_uid, caddy_user.pw_gid)
        log.chmod(0o600)
        # Reuse the installed manager's atomic write, validation, reload and rollback.
        manager = runpy.run_path("/usr/local/sbin/llm-proxy-token")
        manager["write_atomic"](template, updated)
        try:
            manager["apply"](state)
        except Exception:
            manager["write_atomic"](template, previous)
            raise SystemExit("Validation/reload failed; template restored, no credentials printed") from None
        print("Caddy diagnostics installed; token state preserved; backup:", backup)


if __name__ == "__main__":
    main()
