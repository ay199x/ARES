# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Download the pinned GNU Arm toolchain and extract the assembler and linker.

Usage: python tools/fetch_toolchain.py [--platform NAME] [--force] [--keep-archive]

Release, download links and SHA-256 checksums are in tools/toolchain.json.
Only the files listed there for the platform are extracted, into
vendor/<platform>/.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ares.toolchain import platform_tag  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent / "toolchain.json"
STAMP_NAME = "toolchain-version.txt"
CHUNK = 1 << 20


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def download(url, dest, expected_size, expected_sha256):
    """Download url to dest, showing progress; verify size and SHA-256."""
    request = urllib.request.Request(url, headers={"User-Agent": "ares-fetch-toolchain"})
    digest = hashlib.sha256()
    received = 0
    next_report = 10
    with urllib.request.urlopen(request, timeout=60) as response, open(dest, "wb") as out:
        while True:
            chunk = response.read(CHUNK)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            received += len(chunk)
            percent = received * 100 // expected_size if expected_size else 0
            if percent >= next_report:
                print(f"  {percent:3d}%  {received / 1e6:7.1f} MB", flush=True)
                next_report += 10
    if received != expected_size:
        raise SystemExit(f"download size {received} differs from expected {expected_size}")
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise SystemExit(f"SHA-256 mismatch:\n  expected {expected_sha256}\n  actual   {actual}")
    print(f"  SHA-256 verified: {actual}")


def match(name, wanted):
    """The wanted path an archive member stands for, with or without a top folder."""
    name = name.replace("\\", "/")
    if name in wanted:
        return name
    parts = name.split("/", 1)
    if len(parts) == 2 and parts[1] in wanted:
        return parts[1]
    return None


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract(archive, wanted, dest_dir):
    """Extract the members listed in wanted (paths below the top folder)."""
    found = {}
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                rel = match(info.filename, wanted)
                if rel:
                    found[rel] = zf.read(info)
    else:
        with tarfile.open(archive, "r:*") as tf:
            for member in tf.getmembers():
                rel = match(member.name, wanted)
                if rel and (member.isfile() or member.islnk() or member.issym()):
                    found[rel] = tf.extractfile(member).read()
    missing = sorted(set(wanted) - set(found))
    if missing:
        raise SystemExit(f"not found in archive: {', '.join(missing)}")
    for rel, data in found.items():
        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755)
        print(f"  extracted {rel} ({len(data) / 1e6:.1f} MB)")


def verify(dest_dir, files):
    """Run every extracted program with --version."""
    for rel in files:
        if not rel.startswith("bin/") or rel.endswith(".dll"):
            continue
        result = subprocess.run([str(dest_dir / rel), "--version"],
                                capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise SystemExit(f"{rel} --version failed with exit code {result.returncode}")
        print(f"  {result.stdout.splitlines()[0]}")


def main(argv=None):
    config = load_config()
    parser = argparse.ArgumentParser(description="Fetch the GNU assembler and linker.")
    parser.add_argument("--platform", choices=sorted(config["platforms"]),
                        default=None, help="platform to fetch (default: this computer)")
    parser.add_argument("--force", action="store_true",
                        help="download again even if already installed")
    parser.add_argument("--keep-archive", action="store_true",
                        help="keep the downloaded archive in vendor/downloads/")
    args = parser.parse_args(argv)

    tag = args.platform or platform_tag()
    entry = config["platforms"][tag]
    dest_dir = ROOT / "vendor" / tag
    stamp = dest_dir / STAMP_NAME
    files = entry["files"]

    if (not args.force and stamp.is_file()
            and stamp.read_text(encoding="utf-8").strip() == config["version"]
            and all((dest_dir / rel).is_file() for rel in files)):
        print(f"{config['name']} {config['version']} already in {dest_dir}")
        return 0

    archive_name = entry["url"].rsplit("/", 1)[1]
    print(f"{config['name']} {config['version']} for {tag}")
    print(f"  {entry['url']}")
    print(f"  download size {entry['size'] / 1e6:.1f} MB")

    download_dir = ROOT / "vendor" / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    kept = download_dir / archive_name
    work = Path(tempfile.mkdtemp(prefix="fetch-", dir=download_dir))
    try:
        if kept.is_file() and sha256_of(kept) == entry["sha256"]:
            print(f"  using kept archive {kept}")
            archive = kept
        else:
            archive = work / archive_name
            download(entry["url"], archive, entry["size"], entry["sha256"])
            if args.keep_archive:
                os.replace(archive, kept)
                archive = kept
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True)
        extract(archive, set(files), dest_dir)
        if tag == platform_tag():
            verify(dest_dir, files)
        stamp.write_text(config["version"] + "\n", encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"done: {dest_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
