"""Backup engine services: encryption, storage drivers, GFS rotation, and webhook alerts for SportsBall."""

import ctypes
import ctypes.util
import gzip
import io
import ipaddress
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import urllib.parse
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import requests
from django.conf import settings
from django.db import connection
from django.utils import timezone as dj_timezone

from core.models import BackupConfiguration, BackupRecord

logger = logging.getLogger(__name__)

ENCRYPTION_MAGIC = b"SBALLENC1"
LEGACY_MAGIC = b"BLABENC1"


# ---------------------------------------------------------------------------
# 1. AES-256-GCM Encryption / Decryption Layer
# ---------------------------------------------------------------------------

def encrypt_payload(data: bytes, passphrase: str) -> bytes:
    """Encrypt payload using AES-256-GCM with PBKDF2-HMAC-SHA256 key derivation."""
    if not passphrase:
        return data

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    key = kdf.derive(passphrase.encode('utf-8'))
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)

    # Format: MAGIC (9 bytes) + salt (16 bytes) + nonce (12 bytes) + ciphertext (includes 16-byte tag)
    return ENCRYPTION_MAGIC + salt + nonce + ciphertext


def decrypt_payload(data: bytes, passphrase: str) -> bytes:
    """Decrypt an AES-256-GCM encrypted payload, or return as-is if unencrypted."""
    magic_used = None
    if data.startswith(ENCRYPTION_MAGIC):
        magic_used = ENCRYPTION_MAGIC
    elif data.startswith(LEGACY_MAGIC):
        magic_used = LEGACY_MAGIC
    else:
        return data

    if not passphrase:
        raise ValueError("Backup payload is encrypted but no decryption passphrase was provided.")

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    magic_len = len(magic_used)
    salt = data[magic_len:magic_len + 16]
    nonce = data[magic_len + 16:magic_len + 28]
    ciphertext = data[magic_len + 28:]

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    key = kdf.derive(passphrase.encode('utf-8'))
    aesgcm = AESGCM(key)

    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise ValueError("Failed to decrypt backup. Invalid decryption passphrase or corrupted archive.") from exc


# ---------------------------------------------------------------------------
# 2. Storage Drivers: Local, S3, CIFS/SMB, Direct Userspace NFS
# ---------------------------------------------------------------------------

class BaseStorageDriver:
    """Abstract interface for backup storage drivers."""
    def test_connection(self) -> Tuple[bool, str]:
        raise NotImplementedError

    def store_file(self, filename: str, data: bytes) -> None:
        raise NotImplementedError

    def retrieve_file(self, filename: str) -> bytes:
        raise NotImplementedError

    def delete_file(self, filename: str) -> bool:
        raise NotImplementedError


class LocalStorageDriver(BaseStorageDriver):
    """Stores backups on a persistent local filesystem volume (e.g. /backups or BASE_DIR/backups)."""
    def __init__(self, directory: str = "backups"):
        if not os.path.isabs(directory):
            directory = os.path.join(str(settings.BASE_DIR), directory)
        self.directory = directory

    def _ensure_dir(self):
        if not os.path.exists(self.directory):
            os.makedirs(self.directory, mode=0o700, exist_ok=True)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            self._ensure_dir()
            test_file = os.path.join(self.directory, ".test_write.tmp")
            with open(test_file, 'wb') as f:
                f.write(b"test")
            os.remove(test_file)
            return True, f"Local directory '{self.directory}' is writable."
        except Exception as e:
            return False, f"Local storage error: {e}"

    def store_file(self, filename: str, data: bytes) -> None:
        self._ensure_dir()
        target = os.path.join(self.directory, filename)
        with open(target, 'wb') as f:
            f.write(data)
        try:
            os.chmod(target, 0o600)
        except Exception:
            pass

    def retrieve_file(self, filename: str) -> bytes:
        target = os.path.join(self.directory, filename)
        if not os.path.exists(target):
            raise FileNotFoundError(f"Local backup '{filename}' not found.")
        with open(target, 'rb') as f:
            return f.read()

    def delete_file(self, filename: str) -> bool:
        target = os.path.join(self.directory, filename)
        if os.path.exists(target):
            os.remove(target)
            return True
        return False


class S3StorageDriver(BaseStorageDriver):
    """Stores backups on Amazon S3 or S3-compatible endpoints (MinIO, R2, B2)."""
    def __init__(self, config: BackupConfiguration):
        self.config = config
        self.is_mock = os.environ.get('MOCK_MODE', 'False').lower() in ('true', '1', 't')

    def _get_client(self):
        import boto3
        from botocore.config import Config
        return boto3.client(
            's3',
            endpoint_url=self.config.s3_endpoint_url or None,
            aws_access_key_id=self.config.s3_access_key or None,
            aws_secret_access_key=self.config.s3_secret_key or None,
            region_name=self.config.s3_region or 'us-east-1',
            config=Config(signature_version='s3v4')
        )

    def _get_key(self, filename: str) -> str:
        prefix = (self.config.s3_prefix or '').strip('/')
        return f"{prefix}/{filename}" if prefix else filename

    def test_connection(self) -> Tuple[bool, str]:
        if self.is_mock:
            return True, "Mock S3 connection verified."
        try:
            client = self._get_client()
            client.head_bucket(Bucket=self.config.s3_bucket)
            return True, f"Bucket '{self.config.s3_bucket}' reachable."
        except Exception as e:
            return False, f"S3 error: {e}"

    def store_file(self, filename: str, data: bytes) -> None:
        if self.is_mock:
            return
        client = self._get_client()
        key = self._get_key(filename)
        client.put_object(Bucket=self.config.s3_bucket, Key=key, Body=data)

    def retrieve_file(self, filename: str) -> bytes:
        if self.is_mock:
            return b"mock-s3-content"
        client = self._get_client()
        key = self._get_key(filename)
        resp = client.get_object(Bucket=self.config.s3_bucket, Key=key)
        return resp['Body'].read()

    def delete_file(self, filename: str) -> bool:
        if self.is_mock:
            return True
        try:
            client = self._get_client()
            key = self._get_key(filename)
            client.delete_object(Bucket=self.config.s3_bucket, Key=key)
            return True
        except Exception:
            return False


class CIFSStorageDriver(BaseStorageDriver):
    """Pure-Python CIFS/SMB storage driver via smbclient."""
    def __init__(self, config: BackupConfiguration):
        self.config = config
        self.is_mock = os.environ.get('MOCK_MODE', 'False').lower() in ('true', '1', 't')

    def _register_session(self):
        import smbclient
        smbclient.register_session(
            self.config.cifs_server,
            username=self.config.cifs_username,
            password=self.config.cifs_password,
            domain=self.config.cifs_domain or None,
        )

    def _get_path(self, filename: str = "") -> str:
        server = self.config.cifs_server.strip('\\/').replace('/', '\\')
        share = self.config.cifs_share.strip('\\/').replace('/', '\\')
        subpath = (self.config.cifs_subpath or '').strip('\\/').replace('/', '\\')
        base = f"\\\\{server}\\{share}"
        if subpath:
            base = f"{base}\\{subpath}"
        if filename:
            return f"{base}\\{filename}"
        return base

    def test_connection(self) -> Tuple[bool, str]:
        if self.is_mock:
            return True, "Mock SMB connection verified."
        try:
            import smbclient
            self._register_session()
            base_path = self._get_path()
            smbclient.makedirs(base_path, exist_ok=True)
            test_path = f"{base_path}\\.test_write.tmp"
            with smbclient.open_file(test_path, mode="wb") as f:
                f.write(b"test")
            smbclient.remove(test_path)
            return True, f"SMB share '{self.config.cifs_share}' verified."
        except Exception as e:
            return False, f"SMB error: {e}"

    def store_file(self, filename: str, data: bytes) -> None:
        if self.is_mock:
            return
        import smbclient
        self._register_session()
        base_path = self._get_path()
        smbclient.makedirs(base_path, exist_ok=True)
        target = self._get_path(filename)
        with smbclient.open_file(target, mode="wb") as f:
            f.write(data)

    def retrieve_file(self, filename: str) -> bytes:
        if self.is_mock:
            return b"mock-smb-content"
        import smbclient
        self._register_session()
        target = self._get_path(filename)
        with smbclient.open_file(target, mode="rb") as f:
            return f.read()

    def delete_file(self, filename: str) -> bool:
        if self.is_mock:
            return True
        try:
            import smbclient
            self._register_session()
            target = self._get_path(filename)
            smbclient.remove(target)
            return True
        except Exception:
            return False


class UserspaceNFSDriver(BaseStorageDriver):
    """Direct userspace NFS client interacting via libnfs without kernel mounts."""
    def __init__(self, config: BackupConfiguration):
        self.config = config
        self.is_mock = os.environ.get('MOCK_MODE', 'False').lower() in ('true', '1', 't')

    def _get_lib(self):
        try:
            return ctypes.CDLL("libnfs.so.14")
        except OSError:
            libname = ctypes.util.find_library("nfs") or "libnfs.so"
            return ctypes.CDLL(libname)

    def _open_context(self):
        lib = self._get_lib()
        lib.nfs_init_context.restype = ctypes.c_void_p
        ctx = lib.nfs_init_context()
        if not ctx:
            raise RuntimeError("Failed to initialize libnfs context.")

        server_b = self.config.nfs_server.encode('utf-8')
        export_b = self.config.nfs_export.encode('utf-8')

        ret = lib.nfs_mount(ctypes.c_void_p(ctx), server_b, export_b)
        if ret != 0:
            lib.nfs_get_error.restype = ctypes.c_char_p
            err = lib.nfs_get_error(ctypes.c_void_p(ctx)).decode('utf-8', errors='replace')
            lib.nfs_destroy_context(ctypes.c_void_p(ctx))
            raise RuntimeError(f"NFS mount failed: {err}")
        return lib, ctx

    def _get_rel_path(self, filename: str = "") -> str:
        sub = (self.config.nfs_subpath or '').strip('/')
        if sub and filename:
            return f"/{sub}/{filename}"
        elif sub:
            return f"/{sub}"
        elif filename:
            return f"/{filename}"
        return "/"

    def test_connection(self) -> Tuple[bool, str]:
        if self.is_mock:
            return True, "Mock NFS connection verified."
        try:
            lib, ctx = self._open_context()
            try:
                rel = self._get_rel_path()
                lib.nfs_opendir.restype = ctypes.c_void_p
                dir_handle = lib.nfs_opendir(ctypes.c_void_p(ctx), rel.encode('utf-8'))
                if not dir_handle:
                    lib.nfs_get_error.restype = ctypes.c_char_p
                    err = lib.nfs_get_error(ctypes.c_void_p(ctx)).decode('utf-8', errors='replace')
                    return False, f"NFS opendir error: {err}"
                lib.nfs_closedir(ctypes.c_void_p(ctx), ctypes.c_void_p(dir_handle))
                return True, f"NFS export '{self.config.nfs_export}' reachable."
            finally:
                lib.nfs_destroy_context(ctypes.c_void_p(ctx))
        except Exception as e:
            return False, f"NFS connection error: {e}"

    def store_file(self, filename: str, data: bytes) -> None:
        if self.is_mock:
            return
        lib, ctx = self._open_context()
        try:
            rel = self._get_rel_path(filename)
            lib.nfs_open2.restype = ctypes.c_void_p
            fh = lib.nfs_open2(ctypes.c_void_p(ctx), rel.encode('utf-8'), 0x0241, 0o600)
            if not fh:
                lib.nfs_get_error.restype = ctypes.c_char_p
                err = lib.nfs_get_error(ctypes.c_void_p(ctx)).decode('utf-8', errors='replace')
                raise RuntimeError(f"NFS open for write failed: {err}")
            try:
                written = lib.nfs_write(ctypes.c_void_p(ctx), ctypes.c_void_p(fh), ctypes.c_char_p(data), len(data))
                if written < len(data):
                    raise RuntimeError("NFS write incomplete.")
            finally:
                lib.nfs_close(ctypes.c_void_p(ctx), ctypes.c_void_p(fh))
        finally:
            lib.nfs_destroy_context(ctypes.c_void_p(ctx))

    def retrieve_file(self, filename: str) -> bytes:
        if self.is_mock:
            return b"mock-nfs-content"
        lib, ctx = self._open_context()
        try:
            rel = self._get_rel_path(filename)
            lib.nfs_open2.restype = ctypes.c_void_p
            fh = lib.nfs_open2(ctypes.c_void_p(ctx), rel.encode('utf-8'), 0, 0)
            if not fh:
                lib.nfs_get_error.restype = ctypes.c_char_p
                err = lib.nfs_get_error(ctypes.c_void_p(ctx)).decode('utf-8', errors='replace')
                raise RuntimeError(f"NFS open for read failed: {err}")
            try:
                chunks = []
                buf_size = 1024 * 1024
                buf = ctypes.create_string_buffer(buf_size)
                while True:
                    read_bytes = lib.nfs_read(ctypes.c_void_p(ctx), ctypes.c_void_p(fh), buf_size, buf)
                    if read_bytes <= 0:
                        break
                    chunks.append(buf.raw[:read_bytes])
                return b"".join(chunks)
            finally:
                lib.nfs_close(ctypes.c_void_p(ctx), ctypes.c_void_p(fh))
        finally:
            lib.nfs_destroy_context(ctypes.c_void_p(ctx))

    def delete_file(self, filename: str) -> bool:
        if self.is_mock:
            return True
        try:
            lib, ctx = self._open_context()
            try:
                rel = self._get_rel_path(filename)
                ret = lib.nfs_unlink(ctypes.c_void_p(ctx), rel.encode('utf-8'))
                return ret == 0
            finally:
                lib.nfs_destroy_context(ctypes.c_void_p(ctx))
        except Exception:
            return False


def get_storage_driver(config: BackupConfiguration) -> BaseStorageDriver:
    """Factory selecting the storage driver for the active configuration."""
    if config.storage_type == 'S3':
        return S3StorageDriver(config)
    elif config.storage_type == 'CIFS':
        return CIFSStorageDriver(config)
    elif config.storage_type == 'NFS':
        return UserspaceNFSDriver(config)
    return LocalStorageDriver(config.local_path or "backups")


# ---------------------------------------------------------------------------
# 3. GFS Rotation and Webhook Alerts
# ---------------------------------------------------------------------------

def determine_gfs_tier(dt: datetime, config: BackupConfiguration) -> str:
    """Classifies a backup run into Monthly, Weekly, or Daily tier."""
    if config.keep_monthly > 0 and dt.day == config.monthly_day:
        return 'MONTHLY'
    if config.keep_weekly > 0 and dt.weekday() == config.weekly_day:
        return 'WEEKLY'
    return 'DAILY'


def enforce_gfs_retention(config: BackupConfiguration) -> List[str]:
    """Deletes older backups exceeding the retention count for each tier."""
    driver = get_storage_driver(config)
    pruned_files = []

    limits = {
        'DAILY': config.keep_daily,
        'WEEKLY': config.keep_weekly,
        'MONTHLY': config.keep_monthly,
    }

    for tier, keep_count in limits.items():
        if keep_count <= 0:
            continue
        records = list(BackupRecord.objects.filter(tier=tier, status='SUCCESS').order_by('-created_at'))
        if len(records) > keep_count:
            excess = records[keep_count:]
            for rec in excess:
                try:
                    driver.delete_file(rec.filename)
                except Exception as del_err:
                    logger.warning(f"BackupEngine - Failed to delete storage file {rec.filename}: {del_err}")
                pruned_files.append(rec.filename)
                rec.delete()

    return pruned_files


def is_safe_webhook_url(url_str: str) -> bool:
    """Enforce SSRF defenses: Ensure webhook resolves to a valid public IP."""
    try:
        parsed = urllib.parse.urlparse(url_str)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return False
        import socket
        ip_str = socket.gethostbyname(parsed.hostname)
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
        return True
    except Exception:
        return False


def dispatch_webhook_failure(webhook_url: str, error_message: str, tier: str = 'MANUAL') -> None:
    """Dispatches a failure alert to an external webhook (e.g. Discord, Slack, Gotify)."""
    if not webhook_url or not is_safe_webhook_url(webhook_url):
        logger.warning(f"BackupEngine - Webhook skipped: invalid or restricted URL '{webhook_url}'")
        return

    payload = {
        "content": f":warning: **SportsBall Backup Failure Alert**\n"
                   f"**Tier:** {tier}\n"
                   f"**Timestamp:** {dj_timezone.now().isoformat()}\n"
                   f"**Error Details:** ```{error_message}```"
    }
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as exc:
        logger.warning(f"BackupEngine - Failed to deliver webhook alert: {exc}")


# ---------------------------------------------------------------------------
# 4. Backup Execution and Restore Engine
# ---------------------------------------------------------------------------

def _is_sqlite() -> bool:
    engine = settings.DATABASES['default'].get('ENGINE', '')
    return 'sqlite3' in engine


def _get_sqlite_path() -> str:
    db_name = settings.DATABASES['default'].get('NAME')
    return str(db_name)


def _dump_database_payload() -> Tuple[bytes, str]:
    """Extracts raw database bytes and returns (uncompressed_bytes, extension)."""
    if _is_sqlite():
        # Perform live SQLite backup using sqlite3.backup API to avoid locks
        db_path = _get_sqlite_path()
        src_conn = sqlite3.connect(db_path)
        dest_conn = sqlite3.connect(":memory:")
        src_conn.backup(dest_conn)
        src_conn.close()

        # Dump memory connection to bytes
        temp_buffer = io.BytesIO()
        for line in dest_conn.iterdump():
            temp_buffer.write(f"{line}\n".encode('utf-8'))
        dest_conn.close()
        return temp_buffer.getvalue(), "sql"
    else:
        # PostgreSQL dump
        db_conf = settings.DATABASES['default']
        db_name = db_conf.get('NAME', '')
        db_user = db_conf.get('USER', '')
        db_password = db_conf.get('PASSWORD', '')
        db_host = db_conf.get('HOST', 'localhost')
        db_port = str(db_conf.get('PORT', 5432))

        env = os.environ.copy()
        if db_password:
            env['PGPASSWORD'] = db_password

        cmd = [
            'pg_dump',
            '--no-owner',
            '--no-acl',
            '-h', db_host,
            '-p', db_port,
            '-U', db_user,
            db_name,
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        stdout, stderr = proc.communicate(timeout=180)
        if proc.returncode != 0:
            err = stderr.decode('utf-8', errors='replace').strip()
            raise RuntimeError(f"pg_dump failed: {err}")
        return stdout, "sql"


def execute_backup(
    tier: str = 'MANUAL',
    config: Optional[BackupConfiguration] = None,
    progress_callback: Optional[Any] = None
) -> BackupRecord:
    """Executes database dump, compresses, optionally encrypts, and stores the backup snapshot."""
    if config is None:
        config = BackupConfiguration.get_config()

    def update_p(val, msg=""):
        if progress_callback:
            progress_callback(val, status='RUNNING', result_data={'message': msg} if msg else None)

    update_p(10, "Extracting database parameters...")
    timestamp = dj_timezone.now().strftime('%Y%m%d_%H%M%S')
    
    is_encrypted = bool(config.encryption_passphrase)
    ext = "sql.gz"
    base_name = f"sportsball_{tier.lower()}_{timestamp}.{ext}"
    filename = f"{base_name}.enc" if is_encrypted else base_name

    rec = BackupRecord(
        filename=filename,
        tier=tier,
        storage_type=config.storage_type,
        is_encrypted=is_encrypted,
        status='FAILED',
    )

    try:
        update_p(30, "Extracting database snapshot...")
        raw_db_bytes, _ = _dump_database_payload()

        update_p(50, "Compressing payload...")
        compressed_payload = gzip.compress(raw_db_bytes)

        update_p(65, "Encrypting archive..." if is_encrypted else "Packaging archive...")
        final_payload = encrypt_payload(compressed_payload, config.encryption_passphrase) if is_encrypted else compressed_payload

        update_p(80, f"Uploading to {config.get_storage_type_display()}...")
        driver = get_storage_driver(config)
        driver.store_file(filename, final_payload)

        rec.file_size = len(final_payload)
        rec.status = 'SUCCESS'
        rec.save()

        # Update telemetry
        config.last_run_at = dj_timezone.now()
        config.last_status = 'SUCCESS'
        config.last_error = ''
        config.save()

        # Enforce GFS retention if scheduled
        if tier in ('DAILY', 'WEEKLY', 'MONTHLY'):
            update_p(90, "Enforcing GFS retention policy...")
            enforce_gfs_retention(config)

        update_p(100, "Backup protocol completed.")
        logger.info(f"BackupEngine - Successfully created {tier} backup: {filename}")
        return rec

    except Exception as e:
        err_msg = str(e)
        logger.error(f"BackupEngine - Backup failed: {err_msg}", exc_info=True)
        rec.error_message = err_msg
        rec.save()

        config.last_run_at = dj_timezone.now()
        config.last_status = 'FAILED'
        config.last_error = err_msg
        config.save()

        if tier != 'MANUAL' and config.webhook_url:
            dispatch_webhook_failure(config.webhook_url, err_msg, tier=tier)

        raise


def restore_backup(
    record_or_bytes: Any,
    passphrase: Optional[str] = None,
    storage_type: Optional[str] = None,
    filename: Optional[str] = None
) -> None:
    """Restores database from BackupRecord instance or raw file bytes."""
    config = BackupConfiguration.get_config()

    if isinstance(record_or_bytes, BackupRecord):
        rec = record_or_bytes
        driver_type = rec.storage_type
        # Temporarily use record's storage driver
        orig_storage = config.storage_type
        config.storage_type = driver_type
        driver = get_storage_driver(config)
        config.storage_type = orig_storage

        raw_bytes = driver.retrieve_file(rec.filename)
        passphrase = passphrase or config.encryption_passphrase
    else:
        raw_bytes = record_or_bytes
        passphrase = passphrase or config.encryption_passphrase

    # Decrypt if needed
    if raw_bytes.startswith(ENCRYPTION_MAGIC) or raw_bytes.startswith(LEGACY_MAGIC):
        raw_bytes = decrypt_payload(raw_bytes, passphrase)

    # Decompress if gzipped
    if raw_bytes.startswith(b'\x1f\x8b'):
        sql_bytes = gzip.decompress(raw_bytes)
    else:
        sql_bytes = raw_bytes

    # Preserve current config and records if configured
    saved_config = None
    saved_records = []
    if config.preserve_config_on_restore:
        saved_config = {
            'is_enabled': config.is_enabled,
            'backup_time': config.backup_time,
            'weekly_day': config.weekly_day,
            'monthly_day': config.monthly_day,
            'keep_daily': config.keep_daily,
            'keep_weekly': config.keep_weekly,
            'keep_monthly': config.keep_monthly,
            'storage_type': config.storage_type,
            'local_path': config.local_path,
            's3_endpoint_url': config.s3_endpoint_url,
            's3_bucket': config.s3_bucket,
            's3_region': config.s3_region,
            's3_access_key': config.s3_access_key,
            's3_secret_key': config.s3_secret_key,
            's3_prefix': config.s3_prefix,
            'cifs_server': config.cifs_server,
            'cifs_share': config.cifs_share,
            'cifs_subpath': config.cifs_subpath,
            'cifs_username': config.cifs_username,
            'cifs_password': config.cifs_password,
            'cifs_domain': config.cifs_domain,
            'nfs_server': config.nfs_server,
            'nfs_export': config.nfs_export,
            'nfs_subpath': config.nfs_subpath,
            'encryption_passphrase': config.encryption_passphrase,
            'webhook_url': config.webhook_url,
        }
        saved_records = list(BackupRecord.objects.all().values())

    if _is_sqlite():
        # Execute script into database
        connection.close()
        db_path = _get_sqlite_path()
        
        # Write to a fresh sqlite database in memory/temp to verify validity
        sql_text = sql_bytes.decode('utf-8', errors='replace')
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.sqlite3')
        temp_db.close()
        try:
            temp_conn = sqlite3.connect(temp_db.name)
            temp_conn.executescript(sql_text)
            temp_conn.close()
            # Replace target db file
            shutil.copyfile(temp_db.name, db_path)
        finally:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)
    else:
        # PostgreSQL restore
        db_conf = settings.DATABASES['default']
        db_name = db_conf.get('NAME', '')
        db_user = db_conf.get('USER', '')
        db_password = db_conf.get('PASSWORD', '')
        db_host = db_conf.get('HOST', 'localhost')
        db_port = str(db_conf.get('PORT', 5432))

        env = os.environ.copy()
        if db_password:
            env['PGPASSWORD'] = db_password

        cmd = [
            'psql',
            '-h', db_host,
            '-p', db_port,
            '-U', db_user,
            '-d', db_name,
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        stdout, stderr = proc.communicate(input=sql_bytes, timeout=300)
        if proc.returncode != 0:
            err = stderr.decode('utf-8', errors='replace').strip()
            raise RuntimeError(f"psql restore failed: {err}")

    # Re-apply preserved config if desired
    if config.preserve_config_on_restore and saved_config:
        connection.connect()
        cfg = BackupConfiguration.get_config()
        for k, v in saved_config.items():
            setattr(cfg, k, v)
        cfg.save()

        # Re-save backup records
        for r_data in saved_records:
            BackupRecord.objects.update_or_create(uuid=r_data['uuid'], defaults=r_data)
