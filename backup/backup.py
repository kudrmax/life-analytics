import os
import sys
import subprocess
import time
import logging
from datetime import datetime, timezone, timedelta

import yadisk

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("backup")

# ── Config ──

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "db")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "la_user")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "la_password")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "life_analytics")

YADISK_TOKEN = os.environ.get("YADISK_TOKEN", "")
YADISK_BACKUP_PATH = os.environ.get("YADISK_BACKUP_PATH", "/life-analytics-backups/")

BACKUP_PREFIX = os.environ.get("BACKUP_PREFIX", "life_analytics")
BACKUP_INTERVAL_MINUTES = int(os.environ.get("BACKUP_INTERVAL_MINUTES", "360"))
BACKUP_RETAIN_DAYS = int(os.environ.get("BACKUP_RETAIN_DAYS", "30"))

LOCAL_BACKUP_DIR = "/backups"


def create_dump() -> str:
    """Run pg_dump | gzip, return path to .sql.gz file."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{BACKUP_PREFIX}_{ts}.sql.gz"
    os.makedirs(LOCAL_BACKUP_DIR, exist_ok=True)
    filepath = f"{LOCAL_BACKUP_DIR}/{filename}"

    env = os.environ.copy()
    env["PGPASSWORD"] = POSTGRES_PASSWORD

    cmd = (
        f"pg_dump -h {POSTGRES_HOST} -U {POSTGRES_USER} {POSTGRES_DB}"
        f" | gzip > {filepath}"
    )
    result = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr}")

    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    log.info("Dump created: %s (%.2f MB)", filename, size_mb)
    return filepath


def ensure_yadisk_folder(client: yadisk.Client) -> None:
    """Create backup folder on Yandex Disk if it does not exist."""
    path = YADISK_BACKUP_PATH.rstrip("/")
    if not client.exists(path):
        client.mkdir(path)
        log.info("Created Yandex Disk folder: %s", path)


def upload_to_yadisk(client: yadisk.Client, local_path: str) -> None:
    """Upload dump file to Yandex Disk."""
    filename = os.path.basename(local_path)
    remote_path = YADISK_BACKUP_PATH.rstrip("/") + "/" + filename
    client.upload(local_path, remote_path, n_retries=3, retry_interval=5)
    log.info("Uploaded to Yandex Disk: %s", remote_path)


def rotate_old_backups(client: yadisk.Client) -> None:
    """Delete backups older than BACKUP_RETAIN_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=BACKUP_RETAIN_DAYS)
    path = YADISK_BACKUP_PATH.rstrip("/")
    removed = 0

    for item in client.listdir(path):
        if not item.name.endswith(".sql.gz"):
            continue
        if item.modified and item.modified < cutoff:
            client.remove(item.path, permanently=True)
            removed += 1
            log.info("Rotated old backup: %s", item.name)

    if removed:
        log.info("Rotated %d old backup(s)", removed)


def cleanup_local(local_path: str) -> None:
    """Remove local dump file."""
    try:
        os.remove(local_path)
    except OSError:
        pass


def run_backup_cycle() -> None:
    """Execute one full backup cycle. Catches all exceptions."""
    local_path = None
    try:
        local_path = create_dump()

        with yadisk.Client(token=YADISK_TOKEN) as client:
            try:
                client.check_token()
            except yadisk.exceptions.UnauthorizedError:
                log.error(
                    "YADISK_TOKEN is invalid or expired. "
                    "Get a new token at https://yandex.ru/dev/disk/poligon/ "
                    "and set it in .env"
                )
                return

            try:
                ensure_yadisk_folder(client)
                upload_to_yadisk(client, local_path)
            except yadisk.exceptions.YaDiskError as e:
                log.error("Yandex Disk API error during upload: %s", e)
                log.info("Dump saved locally: %s", local_path)
                local_path = None  # keep local file as fallback
                return

            try:
                rotate_old_backups(client)
            except yadisk.exceptions.YaDiskError as e:
                log.warning("Failed to rotate old backups (non-critical): %s", e)

        log.info("Backup cycle complete")
    except subprocess.CalledProcessError:
        log.exception("pg_dump failed")
    except RuntimeError as e:
        log.error("%s", e)
    except Exception:
        log.exception("Backup cycle failed unexpectedly")
    finally:
        if local_path:
            cleanup_local(local_path)


def main() -> None:
    if not YADISK_TOKEN:
        log.error("YADISK_TOKEN is not set. Cannot start backup service.")
        sys.exit(1)

    interval_sec = BACKUP_INTERVAL_MINUTES * 60
    log.info(
        "Backup service started (interval=%d min, retain=%d days, path=%s)",
        BACKUP_INTERVAL_MINUTES,
        BACKUP_RETAIN_DAYS,
        YADISK_BACKUP_PATH,
    )

    # First backup immediately on start
    run_backup_cycle()

    while True:
        log.info("Next backup in %d minutes", BACKUP_INTERVAL_MINUTES)
        time.sleep(interval_sec)
        run_backup_cycle()


if __name__ == "__main__":
    main()
