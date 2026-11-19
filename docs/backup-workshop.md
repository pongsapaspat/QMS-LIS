# QMS-LIS Backup and Restore Workshop

This exercise restores a verified PostgreSQL backup into a separate local database.
It does not modify the Neon production database.

## 1. Prepare PostgreSQL client tools

Open a new PowerShell window and run:

```powershell
$env:Path = "C:\Program Files\PostgreSQL\19\bin;$env:Path"
pg_dump --version
pg_restore --version
psql --version
createdb --version
```

## 2. Verify the backup

From the QMS-LIS project directory:

```powershell
.venv\Scripts\python.exe -m scripts.postgres_backup verify `
  --backup backups\qms-lis-YYYYMMDDTHHMMSSZ.dump
```

Expected result:

```text
Backup verified: backups\qms-lis-YYYYMMDDTHHMMSSZ.dump
```

## 3. Inspect the backup contents

```powershell
pg_restore --list backups\qms-lis-YYYYMMDDTHHMMSSZ.dump
```

Look for tables such as `patients`, `lab_orders`, `results`, `users`, and `audit_logs`.

## 4. Create an empty local restore database

This database is separate from Neon:

```powershell
createdb -U postgres qms_lis_restore_test
```

Enter the local PostgreSQL `postgres` password created during installation.

## 5. Restore the backup

```powershell
.venv\Scripts\python.exe -m scripts.postgres_backup restore `
  --backup backups\qms-lis-YYYYMMDDTHHMMSSZ.dump `
  --database-url "postgresql://postgres:LOCAL_PASSWORD@localhost:5432/qms_lis_restore_test"
```

## 6. Verify restored data

```powershell
psql -U postgres -d qms_lis_restore_test -c "\dt"
psql -U postgres -d qms_lis_restore_test -c "SELECT COUNT(*) FROM patients;"
psql -U postgres -d qms_lis_restore_test -c "SELECT COUNT(*) FROM users;"
```

## 7. Record the restore result

Record the backup timestamp, verification result, restore duration, table checks, and any
problems found. This is the evidence that the backup can actually be used for recovery.

Do not point Render at this local database. It is only a restore test target.
