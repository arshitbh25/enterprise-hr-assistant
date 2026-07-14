"""Unit tests for app/services/storage_service.py."""

from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.storage_service import StoragePathTraversalError, StorageService


@pytest.fixture()
def storage(tmp_path: Path) -> StorageService:
    settings = Settings(_env_file=None, storage_dir=str(tmp_path))
    return StorageService(settings)


def test_save_and_read_round_trip(storage: StorageService):
    storage.save("tenant-a/doc.pdf", b"hello world")

    assert storage.read("tenant-a/doc.pdf") == b"hello world"


def test_save_creates_parent_directories(storage: StorageService, tmp_path: Path):
    storage.save("a/b/c/doc.pdf", b"content")

    assert (tmp_path / "a" / "b" / "c" / "doc.pdf").read_bytes() == b"content"


def test_delete_removes_file(storage: StorageService):
    storage.save("tenant-a/doc.pdf", b"content")

    storage.delete("tenant-a/doc.pdf")

    with pytest.raises(FileNotFoundError):
        storage.read("tenant-a/doc.pdf")


def test_delete_is_a_noop_when_file_already_missing(storage: StorageService):
    storage.delete("never/existed.pdf")  # must not raise


def test_path_traversal_is_rejected(storage: StorageService):
    with pytest.raises(StoragePathTraversalError):
        storage.save("../../etc/passwd", b"malicious")
