#!/usr/bin/python3
"""Certbot deploy hook: atomically install this site's certificate for Caddy."""
import datetime
import grp
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    lineage = Path(os.environ.get('RENEWED_LINEAGE', ''))
    if lineage != Path('/etc/letsencrypt/live/beegame.ru'):
        return
    root = Path('/etc/caddy/certbot/beegame.ru')
    root.mkdir(parents=True, exist_ok=True)
    gid = grp.getgrnam('caddy').gr_gid
    os.chown(root, 0, gid)
    root.chmod(0o750)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    version = Path(tempfile.mkdtemp(prefix=stamp, dir=root))
    os.chown(version, 0, gid)
    version.chmod(0o750)
    for name in ('fullchain.pem', 'privkey.pem'):
        shutil.copyfile(lineage / name, version / name)
        os.chown(version / name, 0, gid)
        (version / name).chmod(0o640)
    cert_key = subprocess.check_output(['openssl', 'x509', '-in', str(version / 'fullchain.pem'), '-pubkey', '-noout'])
    private_key = subprocess.check_output(['openssl', 'pkey', '-in', str(version / 'privkey.pem'), '-pubout'])
    if cert_key != private_key:
        raise RuntimeError('Certificate and key do not match')
    current = root / 'current'
    previous = os.readlink(current) if current.is_symlink() else None
    pending = root / ('pending-' + version.name)
    pending.symlink_to(version.name)
    os.replace(pending, current)
    try:
        subprocess.run(['caddy', 'validate', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile'], check=True, capture_output=True)
        # --force reloads the changed certificate even when the config is identical.
        subprocess.run(['caddy', 'reload', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile', '--force'], check=True, capture_output=True)
    except Exception:
        if previous is not None:
            pending.symlink_to(previous)
            os.replace(pending, current)
            subprocess.run(['caddy', 'reload', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile', '--force'], check=True, capture_output=True)
        else:
            current.unlink()
        raise


if __name__ == '__main__':
    main()
