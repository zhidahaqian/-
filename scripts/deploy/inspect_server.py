"""Emit deployment diagnostics without credentials or individual learning records."""
import importlib.metadata
import json
import os
import platform
import sqlite3
import stat
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path('/data/ds-tutor')
properties = subprocess.check_output([
    'systemctl', 'show', 'ds-tutor',
    '--property=ActiveState,SubState,MainPID,User,UnitFileState,MemoryCurrent,NRestarts',
], text=True)
info = {
    'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
    'python': platform.python_version(),
    'system': platform.platform(),
    'service': dict(line.split('=', 1) for line in properties.splitlines() if '=' in line),
    'server_environment_permissions': oct(stat.S_IMODE((root/'config/server.env').stat().st_mode)),
    'app_has_dotenv_file': (root/'app/.env').exists(),
    'versions': {name: importlib.metadata.version(name) for name in ['streamlit','requests','python-dotenv','pandas']},
}
with urllib.request.urlopen('http://127.0.0.1:8890/_stcore/health', timeout=5) as response:
    info['local_health'] = {'status': response.status, 'body': response.read().decode()}
db = root/'runtime/study.db'
info['database_exists'] = db.exists()
if db.exists():
    with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as connection:
        info['total_submissions'] = connection.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
        info['learner_count'] = connection.execute('SELECT COUNT(DISTINCT learner) FROM attempts').fetchone()[0]
        info['database_integrity'] = connection.execute('PRAGMA quick_check').fetchone()[0]
print(json.dumps(info, ensure_ascii=False, indent=2))
