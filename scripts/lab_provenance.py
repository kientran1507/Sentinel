"""Nonsecret source identity for reproducible local-lab reports."""
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import re
import subprocess


SOURCE_DIRECTORIES = ("services", "scripts", "tests")
SOURCE_FILES = ("pyproject.toml", "setup.cfg", "infrastructure/docker/requirements.lock")
PACKAGES = ("psycopg", "psycopg-binary", "cryptography", "scapy", "zeroconf", "discord.py", "mac-vendor-lookup")


def source_snapshot(root):
    root = Path(root).resolve()
    paths = {path for name in SOURCE_DIRECTORIES for path in (root / name).rglob("*.py")}
    paths.update(root / name for name in SOURCE_FILES if (root / name).is_file())
    files = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("source fingerprint requires regular files within the source root")
        data = path.read_bytes().replace(b"\r\n", b"\n")
        files[path.relative_to(root).as_posix()] = hashlib.sha256(data).hexdigest()
    if not files:
        raise ValueError("source fingerprint has no files")
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"fingerprint_sha256": fingerprint, "files": files, "crlf_normalized": True}


def git_head(root):
    try:
        result = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root,
                                capture_output=True, text=True, timeout=2)
        head = result.stdout.strip()
        return head if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", head) else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def package_versions():
    packages = {}
    for name in PACKAGES:
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return packages


def changed_files(before, after):
    return sorted(name for name in before["files"].keys() | after["files"].keys()
                  if before["files"].get(name) != after["files"].get(name))
