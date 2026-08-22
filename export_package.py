"""
Project Packaging Script
========================
Creates a clean, portable ZIP archive of the Zia Quant platform
excluding temporary files, caches, and heavy virtual environments.
"""

import os
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_ZIP = PROJECT_ROOT.parent / "Zia_Quant_Platform.zip"

EXCLUDE_DIRS = {
    ".venv",
    ".pytest_cache",
    "__pycache__",
    ".git",
    "data/cache",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".log",
}


def package_project():
    print(f"Creating clean ZIP package for Zia at: {OUTPUT_ZIP}")
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            # Prune excluded directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]

            rel_root = Path(root).relative_to(PROJECT_ROOT)
            if any(part in EXCLUDE_DIRS for part in rel_root.parts):
                continue

            for file in files:
                ext = Path(file).suffix
                if ext in EXCLUDE_EXTENSIONS:
                    continue
                if file.endswith(".zip") or file.endswith(".tar.gz"):
                    continue

                file_path = Path(root) / file
                arcname = file_path.relative_to(PROJECT_ROOT)
                zipf.write(file_path, arcname=str(arcname))
                print(f"  + Added: {arcname}")

    print(f"\n[SUCCESS] Package created: {OUTPUT_ZIP} ({OUTPUT_ZIP.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    package_project()
