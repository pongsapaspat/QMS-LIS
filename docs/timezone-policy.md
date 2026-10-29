# Timezone policy

- Database timestamps are stored as UTC instants.
- Internal calculations use timezone-aware UTC `datetime` values.
- SQLite may return naive values; `UTCDateTime` restores UTC metadata at the model boundary.
- Web pages display timestamps in `QMS_LIS_TIMEZONE` (default: `Asia/Bangkok`) and show the offset.
- HTML `datetime-local` values are interpreted as wall-clock time in the configured application timezone, then converted to UTC before persistence.
- API timestamp inputs must include `Z` or an explicit numeric offset. Naive API timestamps are rejected.
- API responses serialize timestamps in UTC ISO-8601 form (`Z` or its equivalent `+00:00`).
- Date-only values, such as date of birth, are not timezone-converted.

Example: web input `2026-10-28T14:30` is interpreted as Asia/Bangkok and stored/returned as the UTC instant `2026-10-28T07:30:00Z`.
