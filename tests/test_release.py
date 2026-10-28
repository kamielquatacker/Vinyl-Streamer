import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from scripts.package_release import DIRECTORIES, REQUIRED, TEXT_SUFFIXES, TOP_LEVEL, build_release, verify_archive


@pytest.fixture
def release_root(tmp_path):
    for name in DIRECTORIES:
        (tmp_path / name).mkdir()
    for name in TOP_LEVEL + REQUIRED:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0.1.0\n" if name == "VERSION" else b"example\r\n")
    return tmp_path


def test_release_has_valid_checksum_manifest_and_no_local_files(release_root):
    for name in ["app/__pycache__/test.pyc", "app/.env", "app/.venv/secret.txt", "app/local.log"]:
        path = release_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not for upload")
    archive, checksum = build_release(release_root)
    assert checksum.read_text().split()[0] == hashlib.sha256(archive.read_bytes()).hexdigest()
    with tarfile.open(archive, "r:gz") as package:
        names = package.getnames()
        assert all(name not in names for name in ["app/__pycache__/test.pyc", "app/.env", "app/.venv/secret.txt", "app/local.log"])
        manifest = json.load(package.extractfile("RELEASE.json"))
        assert manifest["version"] == "0.1.0"
        for name, expected_hash in manifest["files"].items():
            data = package.extractfile(name).read()
            assert hashlib.sha256(data).hexdigest() == expected_hash
            if Path(name).suffix in TEXT_SUFFIXES or name == "VERSION":
                assert b"\r\n" not in data
            else:
                # Binary assets must keep their original bytes, including CRLF sequences.
                assert data == (release_root / name).read_bytes()


def test_same_sources_produce_same_archive(release_root):
    first, _ = build_release(release_root)
    before = first.read_bytes()
    second, _ = build_release(release_root)
    assert second.read_bytes() == before


def test_corrupt_archive_is_rejected(tmp_path):
    path = tmp_path / "bad.tar.gz"
    path.write_bytes(b"\x00" * 100)
    with pytest.raises(ValueError, match="Invalid release archive"):
        verify_archive(path, {})


def test_missing_required_file_is_rejected(release_root):
    (release_root / REQUIRED[0]).unlink()
    with pytest.raises(ValueError, match="Required release file"):
        build_release(release_root)


@pytest.mark.parametrize("version", ["../wrong", "0.1", "v0.1.0"])
def test_invalid_version_is_rejected(release_root, version):
    (release_root / "VERSION").write_text(version)
    with pytest.raises(ValueError, match="VERSION"):
        build_release(release_root)


def test_modified_archive_contents_are_rejected(tmp_path):
    path = tmp_path / "changed.tar.gz"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        member = tarfile.TarInfo("file.txt")
        member.size = 7
        archive.addfile(member, io.BytesIO(b"changed"))
    path.write_bytes(gzip.compress(buffer.getvalue()))
    with pytest.raises(ValueError, match="content mismatch"):
        verify_archive(path, {"file.txt": b"original"})
