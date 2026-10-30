#!/usr/bin/env bash
# Ubuntu installation for the application's dedicated /data/ds-tutor directory.
# Upload the source archive and a root-readable config/server.env before running.
set -euo pipefail
APP_ROOT=/data/ds-tutor
ARCHIVE=${1:?Usage: bash muliao_install.sh /absolute/path/source.zip}
if [ "$(id -u)" -ne 0 ]; then
  printf 'Run this installation script as root.\n' >&2
  exit 1
fi
test -f "$ARCHIVE"
test -s "$APP_ROOT/config/server.env"
if ! systemctl is-active --quiet ds-tutor && ss -H -ltn 'sport = :8890' | /usr/bin/python3 -c 'import sys; sys.exit(0 if sys.stdin.read().strip() else 1)'; then
  printf 'Port 8890 is already occupied; no application was replaced.\n' >&2
  exit 1
fi
install -d -m 755 "$APP_ROOT" "$APP_ROOT/app"
if ! id ds-tutor >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$APP_ROOT/runtime" --shell /usr/sbin/nologin ds-tutor
fi
install -d -m 750 -o ds-tutor -g ds-tutor "$APP_ROOT/runtime"
if [ -f "$APP_ROOT/app/app.py" ]; then
  install -d -m 700 "$APP_ROOT/backups"
  tar -czf "$APP_ROOT/backups/app-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" -C "$APP_ROOT" app
fi
/usr/bin/python3 - "$ARCHIVE" "$APP_ROOT/app" <<'PY'
import sys, zipfile
from pathlib import Path
source, target = Path(sys.argv[1]), Path(sys.argv[2]).resolve()
with zipfile.ZipFile(source) as archive:
    for name in archive.namelist():
        output = (target / name).resolve()
        if not output.is_relative_to(target):
            raise ValueError('Unsafe archive member')
        if Path(name).name == '.env' or name.startswith(('runtime/', '.venv/')):
            raise ValueError('Runtime state must not be included in the source archive')
    archive.extractall(target)
for path in target.rglob('*'):
    path.chmod(0o755 if path.is_dir() else 0o644)
PY
if [ ! -x "$APP_ROOT/venv/bin/python" ]; then
  if ! /usr/bin/python3 -c 'import ensurepip' >/dev/null 2>&1; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv
  fi
  /usr/bin/python3 -m venv "$APP_ROOT/venv"
fi
"$APP_ROOT/venv/bin/python" -m pip install --disable-pip-version-check --index-url "${PIP_INDEX_URL:-https://pypi.org/simple}" -r "$APP_ROOT/app/requirements.txt"
"$APP_ROOT/venv/bin/python" -m compileall -q "$APP_ROOT/app/app.py" "$APP_ROOT/app/ds_tutor"
install -m 644 "$APP_ROOT/app/scripts/deploy/ds-tutor.service" /etc/systemd/system/ds-tutor.service
systemctl daemon-reload
systemctl enable ds-tutor
systemctl restart ds-tutor
"$APP_ROOT/venv/bin/python" - <<'PY'
import time, urllib.request
for _ in range(30):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8890/_stcore/health', timeout=2) as response:
            if response.read() == b'ok':
                print('Application health: ok')
                break
    except OSError:
        pass
    time.sleep(1)
else:
    raise SystemExit('Application did not become healthy; inspect journalctl -u ds-tutor.')
PY
systemctl is-active ds-tutor
systemctl is-enabled ds-tutor
