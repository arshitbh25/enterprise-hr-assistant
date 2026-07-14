"""Local-filesystem document storage (SDD Section 9: storage_service.py).

Rooted at settings.storage_dir; the local -> S3-compatible swap (SDD
Section 8.1 scale path) touches only this module. Storage keys are
always server-generated (tenant_id/content_hash_filename, built in the
upload route) rather than derived from raw user input alone, but this
still rejects any path escaping the storage root as defense in depth
(SDD Section 11.7).
"""

from pathlib import Path

from app.core.config import Settings


class StoragePathTraversalError(ValueError):
    """Raised if a storage key would resolve outside the storage root.

    Storage keys are always server-generated, so this indicates a bug,
    not a user-triggerable condition - it is not a DomainError/HTTP
    concern.
    """


class StorageService:
    def __init__(self, settings: Settings) -> None:
        self._root = Path(settings.storage_dir).resolve()

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self._root / relative_path).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StoragePathTraversalError(
                f"Storage path escapes the storage root: {relative_path!r}"
            )
        return candidate

    def save(self, relative_path: str, content: bytes) -> None:
        path = self._resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def read(self, relative_path: str) -> bytes:
        return self._resolve(relative_path).read_bytes()

    def delete(self, relative_path: str) -> None:
        self._resolve(relative_path).unlink(missing_ok=True)
