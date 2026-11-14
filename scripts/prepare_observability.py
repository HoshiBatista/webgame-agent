"""Create private secrets idempotently. Never prints or overwrites a credential."""
import argparse
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('.data/observability-secrets'))
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.directory.chmod(0o700)
    for name in ['grafana_admin_password', 'metrics_db_password']:
        path = args.directory / name
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or len(path.read_text().strip()) < 24:
                raise SystemExit('Existing secret is invalid; refusing to overwrite it.')
            path.chmod(0o600)
            continue
        with os.fdopen(fd, 'w') as handle:
            handle.write(secrets.token_urlsafe(36) + '\n')
    print('Private observability secrets are ready. Existing values were preserved.')


if __name__ == '__main__':
    main()
