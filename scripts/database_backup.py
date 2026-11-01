import argparse
import hashlib
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

from app.core.config import get_settings

logger = logging.getLogger("qms_lis.backup")


@dataclass(frozen=True)
class BackupManifest:
    created_at: str
    source_database: str
    backup_file: str
    sha256: str
    integrity_check: str


def sqlite_path_from_database_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError(
            "automatic backup supports only a file-based SQLite DATABASE_URL; "
            "use --database for an explicit SQLite file"
        )
    raw_path = unquote(database_url.removeprefix(prefix).split("?", maxsplit=1)[0])
    if not raw_path or raw_path == ":memory:":
        raise ValueError("an in-memory SQLite database cannot be backed up to a file")
    return Path(raw_path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_integrity_check(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"database file not found: {path}")
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {result}")
    return "ok"


def verify_sqlite_backup(backup_path: Path) -> BackupManifest | None:
    sqlite_integrity_check(backup_path)
    manifest_path = backup_path.with_suffix(backup_path.suffix + ".json")
    if not manifest_path.is_file():
        return None
    manifest = BackupManifest(**json.loads(manifest_path.read_text(encoding="utf-8")))
    checksum = sha256_file(backup_path)
    if checksum != manifest.sha256:
        raise RuntimeError("backup checksum does not match its manifest")
    return manifest


def backup_sqlite(source: Path, output_directory: Path) -> tuple[Path, Path]:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source database not found: {source}")
    sqlite_integrity_check(source)
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = output_directory.resolve() / f"{source.stem}-{timestamp}.sqlite3"
    if backup_path.exists():
        raise FileExistsError(f"backup already exists: {backup_path}")

    with (
        sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_connection,
        sqlite3.connect(backup_path) as backup_connection,
    ):
        source_connection.backup(backup_connection)

    integrity = sqlite_integrity_check(backup_path)
    manifest = BackupManifest(
        created_at=datetime.now(UTC).isoformat(),
        source_database=source.name,
        backup_file=backup_path.name,
        sha256=sha256_file(backup_path),
        integrity_check=integrity,
    )
    manifest_path = backup_path.with_suffix(backup_path.suffix + ".json")
    manifest_path.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("backup_created file=%s", backup_path.name)
    return backup_path, manifest_path


def restore_sqlite(backup_path: Path, target: Path) -> Path:
    backup_path = backup_path.resolve()
    target = target.resolve()
    verify_sqlite_backup(backup_path)
    if target.exists():
        raise FileExistsError(f"restore target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True) as source_connection,
            sqlite3.connect(target) as target_connection,
        ):
            source_connection.backup(target_connection)
        sqlite_integrity_check(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    logger.info("backup_restored target=%s", target.name)
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backup, verify, or restore QMS-LIS SQLite")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument(
        "--database",
        type=Path,
        help="SQLite file (default: resolve QMS_LIS_DATABASE_URL from .env)",
    )
    backup_parser.add_argument("--output-directory", type=Path, default=Path("backups"))

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--backup", type=Path, required=True)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", type=Path, required=True)
    restore_parser.add_argument("--target", type=Path, required=True)
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    if args.command == "backup":
        database = args.database or sqlite_path_from_database_url(get_settings().database_url)
        backup_path, manifest_path = backup_sqlite(database, args.output_directory)
        print(f"Backup: {backup_path}")
        print(f"Manifest: {manifest_path}")
    elif args.command == "verify":
        verify_sqlite_backup(args.backup)
        print(f"Backup verified: {args.backup}")
    else:
        restored = restore_sqlite(args.backup, args.target)
        print(f"Database restored: {restored}")


if __name__ == "__main__":
    main()
