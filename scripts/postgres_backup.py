"""Create, verify, and restore PostgreSQL custom-format backups."""

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings


@dataclass(frozen=True)
class BackupManifest:
    created_at: str
    source_database: str
    backup_file: str
    sha256: str
    format: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(
            f"{name} was not found. Install PostgreSQL client tools before running this command."
        )


def pgtools_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def backup(database_url: str, output_directory: Path) -> tuple[Path, Path]:
    require_tool("pg_dump")
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = output_directory / f"qms-lis-{timestamp}.dump"
    manifest_path = backup_path.with_suffix(".json")
    subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--file",
            str(backup_path),
            "--dbname",
            pgtools_url(database_url),
        ],
        check=True,
    )
    manifest = BackupManifest(
        created_at=datetime.now(UTC).isoformat(),
        source_database="QMS-LIS PostgreSQL",
        backup_file=backup_path.name,
        sha256=sha256_file(backup_path),
        format="custom",
    )
    manifest_path.write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")
    return backup_path, manifest_path


def verify(backup_path: Path) -> None:
    require_tool("pg_restore")
    manifest_path = backup_path.with_suffix(".json")
    if not backup_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("backup file and matching JSON manifest are required")
    manifest = BackupManifest(**json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.sha256 != sha256_file(backup_path):
        raise RuntimeError("backup checksum does not match its manifest")
    subprocess.run(["pg_restore", "--list", str(backup_path)], check=True, capture_output=True)


def restore(backup_path: Path, database_url: str) -> None:
    require_tool("pg_restore")
    verify(backup_path)
    subprocess.run(
        [
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--dbname",
            pgtools_url(database_url),
            str(backup_path),
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="QMS-LIS PostgreSQL backup utility")
    commands = parser.add_subparsers(dest="command", required=True)
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument("--output-directory", type=Path, default=Path("backups"))
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--backup", type=Path, required=True)
    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("--backup", type=Path, required=True)
    restore_parser.add_argument("--database-url", required=True)
    args = parser.parse_args()

    if args.command == "backup":
        path, manifest = backup(get_settings().database_url, args.output_directory)
        print(f"Backup: {path}\nManifest: {manifest}")
    elif args.command == "verify":
        verify(args.backup)
        print(f"Backup verified: {args.backup}")
    else:
        restore(args.backup, args.database_url)
        print(f"Backup restored: {args.backup}")


if __name__ == "__main__":
    main()
