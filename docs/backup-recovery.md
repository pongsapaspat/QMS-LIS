# Database backup and recovery

## SQLite development database

Stop application writes before restore operations. A backup can be created while the application is
running because the script uses the SQLite Backup API and verifies the resulting file.

```powershell
.venv\Scripts\python.exe -m scripts.database_backup backup `
  --output-directory backups
```

The database path is read automatically from `QMS_LIS_DATABASE_URL` in `.env`. Use
`--database path\to\database.sqlite3` only when backing up a different SQLite file.

Each backup has a JSON manifest containing its UTC creation time, SHA-256 checksum, and integrity
check result. Verify it before moving or restoring it:

```powershell
.venv\Scripts\python.exe -m scripts.database_backup verify `
  --backup backups\qms_lis_dev-YYYYMMDDTHHMMSSZ.sqlite3
```

Restore always requires a new target path and refuses to overwrite an existing database:

```powershell
.venv\Scripts\python.exe -m scripts.database_backup restore `
  --backup backups\qms_lis_dev-YYYYMMDDTHHMMSSZ.sqlite3 `
  --target restored\qms_lis_dev.sqlite3
```

After restore, point `QMS_LIS_DATABASE_URL` at the restored file and run:

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic check
```

## PostgreSQL production database

Use PostgreSQL native tools so roles, constraints, indexes, and transaction consistency are retained:

```powershell
pg_dump --format=custom --file=qms_lis.dump --dbname=$env:QMS_LIS_DATABASE_URL
pg_restore --list qms_lis.dump
createdb qms_lis_restore_test
pg_restore --exit-on-error --dbname=qms_lis_restore_test qms_lis.dump
```

Run `alembic upgrade head`, `alembic check`, and the readiness endpoint against the restored database.
Keep encrypted backups outside the application host, restrict access to authorized operators, define a
retention period, and perform a documented restore test regularly.
