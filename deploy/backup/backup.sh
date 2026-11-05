#!/bin/sh
# Dump the database, encrypt it to a public key, and upload it.
# Nothing here can decrypt a backup, so a compromised server can't read old ones.
set -eu

: "${PGHOST:?}" "${PGUSER:?}" "${PGPASSWORD:?}" "${PGDATABASE:?}"
: "${AGE_PUBLIC_KEY:?}" "${BACKUP_REMOTE:?}"

name="make-the-teams-$(date -u +%Y-%m-%dT%H-%M-%SZ).dump.age"
file="${TMPDIR:-/tmp}/$name"
trap 'rm -f "$file" "$file.plain"' EXIT

# Dumping to a file first means a failed dump can't upload a partial backup. In a pipe,
# set -e would only see the last command fail.
pg_dump --format=custom --file="$file.plain"
age --recipient "$AGE_PUBLIC_KEY" --output "$file" "$file.plain"
rm -f "$file.plain"

rclone copyto --s3-no-check-bucket "$file" "$BACKUP_REMOTE/$name"

# Confirm the upload exists and is the expected size before reporting success.
expected=$(wc -c < "$file" | tr -d ' ')
actual=$(rclone size --json "$BACKUP_REMOTE/$name" | sed -E 's/.*"bytes":([0-9]+).*/\1/')
if [ "$expected" != "$actual" ]; then
  echo "Upload size mismatch: expected $expected bytes, found $actual" >&2
  exit 1
fi
echo "Backed up $name ($expected bytes)"
