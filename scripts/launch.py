"""一键入口：已有服务则打开网页，否则启动服务并等待用户退出。"""
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
url = "http://127.0.0.1:8501"
try:
    with urllib.request.urlopen(url + "/_stcore/health", timeout=2) as response:
        running = response.read() == b"ok"
except (urllib.error.URLError, OSError):
    running = False
if running:
    print("A Streamlit service is already running at " + url)
    webbrowser.open(url)
else:
    print("Starting Data Structures Tutor at " + url)
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
                    "--server.port", "8501", "--server.headless", "false"], cwd=ROOT, check=True)
