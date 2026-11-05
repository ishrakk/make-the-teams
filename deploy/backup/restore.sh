#!/bin/sh
# Decrypt a backup and restore it into a database. Run this on your own computer, which
# holds the private key. The server never has it.
#
#   deploy/backup/restore.sh backup.dump.age key.txt postgresql://teams:pw@localhost/teams
set -eu

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <backup.dump.age> <age key file> <database URL>" >&2
  exit 2
fi
backup=$1
key=$2
database=$3

plain=$(mktemp)
trap 'rm -f "$plain"' EXIT
age --decrypt --identity "$key" --output "$plain" "$backup"
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$database" "$plain"
echo "Restored $backup"
