import sqlite3
from pathlib import Path

import pytest

from scripts.database_backup import (
    backup_sqlite,
    restore_sqlite,
    sqlite_path_from_database_url,
    verify_sqlite_backup,
)


def create_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE samples (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO samples (value) VALUES ('verified')")


def test_backup_verify_and_restore_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    create_database(source)

    backup, manifest = backup_sqlite(source, tmp_path / "backups")
    assert backup.is_file()
    assert manifest.is_file()
    assert verify_sqlite_backup(backup) is not None

    restored = restore_sqlite(backup, tmp_path / "restored.sqlite3")
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT value FROM samples").fetchone() == ("verified",)


def test_restore_refuses_to_overwrite_existing_database(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "existing.sqlite3"
    create_database(source)
    create_database(target)
    backup, _ = backup_sqlite(source, tmp_path / "backups")

    with pytest.raises(FileExistsError, match="already exists"):
        restore_sqlite(backup, target)


def test_sqlite_path_from_database_url() -> None:
    assert sqlite_path_from_database_url("sqlite:///./qms_lis_dev.sqlite3") == Path(
        "qms_lis_dev.sqlite3"
    )


def test_sqlite_path_from_database_url_rejects_non_sqlite_database() -> None:
    with pytest.raises(ValueError, match="supports only"):
        sqlite_path_from_database_url("postgresql://localhost/qms_lis")
