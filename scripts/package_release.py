#!/usr/bin/env python3
"""Build a verified upload archive using only the Python standard library."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = ("README.md", "VERSION", "requirements.txt", "requirements-dev.txt", "pytest.ini")
DIRECTORIES = ("app", "scripts", "tests", "deploy", "docs")
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".txt", ".ini", ".service"}
EXCLUDED = {"__pycache__", "venv", "artifacts", "node_modules"}
REQUIRED = ("app/api.py", "app/static/index.html", "scripts/run_server.py", "deploy/vinyl-streamer-app.service")


def source_files(root: Path) -> dict[str, bytes]:
    paths = [root / name for name in TOP_LEVEL]
    for name in DIRECTORIES:
        directory = root / name
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"Missing directory or unexpected symlink: {name}")
        for path in directory.rglob("*"):
            parts = path.relative_to(root).parts
            if any(part.startswith(".") or part in EXCLUDED for part in parts):
                continue
            if path.is_symlink():
                raise ValueError(f"Release sources must not contain symlinks: {path}")
            if path.is_file() and path.suffix not in {".pyc", ".pyo", ".log"}:
                paths.append(path)
    payloads = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing file or unexpected symlink: {path}")
        data = path.read_bytes()
        if path.suffix in TEXT_SUFFIXES or path.name == "VERSION":
            data = data.replace(b"\r\n", b"\n")
        payloads[path.relative_to(root).as_posix()] = data
    for name in REQUIRED:
        if name not in payloads:
            raise ValueError(f"Required release file is missing: {name}")
    return payloads


def verify_archive(path: Path, expected: dict[str, bytes]) -> None:
    """Check gzip integrity, the exact file list, and every file's contents."""
    try:
        raw = gzip.decompress(path.read_bytes())
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)) or set(names) != set(expected):
                raise ValueError("Archive file list does not match the source files")
            for member in members:
                if not member.isfile() or archive.extractfile(member).read() != expected[member.name]:
                    raise ValueError(f"Archive content mismatch: {member.name}")
    except (OSError, EOFError, tarfile.TarError, zlib.error) as exc:
        raise ValueError(f"Invalid release archive: {exc}") from exc


def build_release(root: Path) -> tuple[Path, Path]:
    root = root.resolve()
    payloads = source_files(root)
    version = payloads["VERSION"].decode("utf-8").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("VERSION must contain a version such as 0.1.0")
    manifest = {
        "version": version,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payloads.items())},
    }
    payloads["RELEASE.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_dir = root / "artifacts"
    output_dir.mkdir(exist_ok=True)
    output = output_dir / f"vinyl-streamer-{version}.tar.gz"
    temporary = None
    checksum_temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_dir, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            # Fixed headers and sorted paths make identical source produce identical bytes.
            with gzip.GzipFile(filename="", fileobj=file, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for name, data in sorted(payloads.items()):
                        info = tarfile.TarInfo(name)
                        info.size = len(data)
                        info.mode = 0o644
                        archive.addfile(info, io.BytesIO(data))
        verify_archive(temporary, payloads)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        checksum = output.with_name(output.name + ".sha256")
        with tempfile.NamedTemporaryFile(dir=output_dir, mode="w", encoding="utf-8", newline="\n", suffix=".tmp", delete=False) as file:
            checksum_temporary = Path(file.name)
            file.write(f"{digest}  {output.name}\n")
        os.replace(temporary, output)
        os.replace(checksum_temporary, checksum)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if checksum_temporary is not None:
            checksum_temporary.unlink(missing_ok=True)
    return output, checksum


def main() -> None:
    try:
        archive, checksum = build_release(ROOT)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Release failed: {exc}") from exc
    print(f"Verified archive: {archive}")
    print(f"Checksum file:    {checksum}")
    print(checksum.read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    main()
