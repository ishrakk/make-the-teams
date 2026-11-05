# Tools for the backup job: pg_dump, age for encryption, rclone for upload.
FROM postgres:16-alpine
RUN apk add --no-cache age rclone
COPY backup.sh /usr/local/bin/backup.sh
USER 70
ENTRYPOINT ["/usr/local/bin/backup.sh"]
