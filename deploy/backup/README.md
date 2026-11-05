# Backups

Each night, a Kubernetes CronJob dumps the database, encrypts the dump to a public key with
[age](https://age-encryption.org), and uploads it to Cloudflare R2.

| File | Purpose |
| --- | --- |
| [`backup.sh`](backup.sh) | Dumps, encrypts, uploads and checks the upload. |
| [`restore.sh`](restore.sh) | Decrypts a backup and restores it. Run on your own computer. |
| [`Dockerfile`](Dockerfile) | The job's image: `pg_dump`, `age` and `rclone`. |

## Keeping backups safe

- **The server can only encrypt.** The private key stays in your password manager, so someone
  who breaks into the VM can't read old backups.
- **Keep `RATING_SECRET` apart from backups.** A leaked backup then can't reveal who gave a rating.
- **Backups hold personal data:** emails and password hashes, so they're encrypted before upload.
- **A failed dump uploads nothing,** and the job checks the uploaded size before reporting success.

## Restoring

1. Download a backup from your R2 bucket.
2. Stop the site, so nothing writes during the restore:
   ```bash
   kubectl -n make-the-teams scale deployment/web --replicas=0
   ```
3. Tunnel to the database. On your computer, then in that SSH session:
   ```bash
   ssh -L 5432:localhost:5432 opc@<VM IP>
   kubectl -n make-the-teams port-forward service/postgres 5432:5432
   ```
4. Restore from your computer, which needs `age` and PostgreSQL 16 client tools:
   ```bash
   deploy/backup/restore.sh make-the-teams-....dump.age key.txt \
     "postgresql://teams:<POSTGRES_PASSWORD>@localhost/teams"
   ```
5. Start the site again:
   ```bash
   kubectl -n make-the-teams scale deployment/web --replicas=2
   ```

`--clean` in the restore replaces the tables in that database. Check that you're pointing at
the right one.

**Practice this before you need it.** A backup you haven't restored isn't proven.

## Status

Backup and restore were tested end to end against a real PostgreSQL 16 database, with real
`age`, using a local folder in place of R2. Row counts matched and the schema matched the
migrations. A failed dump uploaded nothing. The job hasn't yet run against R2 or in a cluster.

**Nothing alerts you if the nightly job fails yet.** Check it with:

```bash
kubectl -n make-the-teams get jobs
```
