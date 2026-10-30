"""打包可提交/上传云 GPU 的项目，不包含密钥、学习记录或虚拟环境。"""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "deliverables/数据结构智练_项目源码.zip"
FILES = ["app.py", "README.md", "requirements.txt", "requirements-dev.txt", "requirements-lock.txt",
         ".env.example", ".gitignore", ".gitattributes", ".streamlit/config.toml", "启动应用.cmd"]
FOLDERS = ["ds_tutor", "assets", "data", "training", "scripts", "tests", "docs"]

OUTPUT.parent.mkdir(exist_ok=True)
with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
    for name in FILES:
        path = ROOT / name
        if path.is_file():
            archive.write(path, path.relative_to(ROOT).as_posix())
    for folder in FOLDERS:
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, path.relative_to(ROOT).as_posix())
print(f"Packaged {OUTPUT.name}: {OUTPUT.stat().st_size:,} bytes")
