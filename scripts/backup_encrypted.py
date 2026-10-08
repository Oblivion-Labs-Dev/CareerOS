"""Encrypted backup of Career OS data that is not committed in plain text.

The repository is public, so personal data (the database, application and
submission records, screenshots, career.json, resume templates, answer
manifests) is committed only as AES-256-GCM encrypted parts under
backups/encrypted/. The key never enters the repository: it lives in
~/.careeros/backup.key (override with CAREEROS_BACKUP_KEY_FILE). Without that
key the backup cannot be restored, so keep a copy of it somewhere safe.

    python scripts/backup_encrypted.py backup
    python scripts/backup_encrypted.py verify
    python scripts/backup_encrypted.py restore --to D:\\careeros-restore

Requires the `cryptography` package (in apps/api/requirements.txt).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import secrets
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from contextlib import closing
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "backups" / "encrypted"
PART_SIZE = 45 * 1024 * 1024
FORMAT = "careeros-backup-v1"

PRIVATE_PATHS = [
    "apps/api/data",
    "logs",
    "evals/resume/results",
    "data/profile/career.json",
    "data/profile/career.md",
    "data/candidate_answers_manifest.json",
    "data/autonomous_batch_results.json",
    "templates",
    "apps/web/public/resumes",
]
# Live browser sessions and cookies stay out even when encrypted.
EXCLUDED_DIRS = {"browser_profile", ".auth"}
DATABASE = "apps/api/data/career_os.db"
SQLITE_SIDECARS = (DATABASE, DATABASE + "-wal", DATABASE + "-shm", DATABASE + "-journal")


def key_path() -> Path:
    return Path(os.environ.get("CAREEROS_BACKUP_KEY_FILE") or Path.home() / ".careeros" / "backup.key")


def load_key(create: bool) -> bytes:
    path = key_path()
    if path.exists():
        key = base64.b64decode(path.read_text().strip())
        if len(key) != 32:
            sys.exit(f"{path} does not hold a 256-bit key.")
        return key
    if not create:
        sys.exit(f"No backup key at {path}. Copy the key you saved there, or set CAREEROS_BACKUP_KEY_FILE.")
    path.parent.mkdir(parents=True, exist_ok=True)
    key = AESGCM.generate_key(bit_length=256)
    path.write_text(base64.b64encode(key).decode() + "\n")
    print(f"Created a new backup key at {path}. Copy it somewhere safe: without it this backup cannot be restored.")
    return key


def _excluded(rel: str) -> bool:
    parts = Path(rel).parts
    return rel in SQLITE_SIDECARS or any(p in EXCLUDED_DIRS for p in parts)


def _add_database(tar: tarfile.TarFile, scratch: Path) -> None:
    source = REPO_ROOT / DATABASE
    if not source.exists():
        return
    snapshot = scratch / "career_os.db"
    with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as src, \
            closing(sqlite3.connect(snapshot)) as dst:
        src.backup(dst)
        rows = src.execute("SELECT key, value FROM kv_store").fetchall()
    tar.add(snapshot, arcname=DATABASE)
    exported = {key: _json_or_text(value) for key, value in rows}
    data = json.dumps(exported, indent=1, ensure_ascii=False, default=str).encode()
    info = tarfile.TarInfo("kv_store_export.json")
    info.size = len(data)
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))


def _json_or_text(value):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def build_archive(target: Path, scratch: Path) -> int:
    count = 0
    with tarfile.open(target, "w:gz", compresslevel=6) as tar:
        _add_database(tar, scratch)
        for rel_root in PRIVATE_PATHS:
            root = REPO_ROOT / rel_root
            if root.is_file():
                tar.add(root, arcname=rel_root)
                count += 1
                continue
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                rel = path.relative_to(REPO_ROOT).as_posix()
                if path.is_file() and not _excluded(rel):
                    tar.add(path, arcname=rel)
                    count += 1
    return count


def backup() -> None:
    key = load_key(create=True)
    backup_id = time.strftime("%Y%m%dT%H%M%S")
    with tempfile.TemporaryDirectory(prefix="careeros-backup-") as tmp:
        scratch = Path(tmp)
        archive = scratch / "backup.tar.gz"
        files = build_archive(archive, scratch)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if OUT_DIR.exists():
            shutil.rmtree(OUT_DIR)
        OUT_DIR.mkdir(parents=True)
        aead = AESGCM(key)
        parts = []
        with archive.open("rb") as fh:
            index = 0
            while chunk := fh.read(PART_SIZE):
                nonce = secrets.token_bytes(12)
                sealed = nonce + aead.encrypt(nonce, chunk, f"{backup_id}:{index}".encode())
                name = f"part-{index:04d}.bin"
                (OUT_DIR / name).write_bytes(sealed)
                parts.append({"file": name, "sha256": hashlib.sha256(sealed).hexdigest()})
                index += 1
    manifest = {"format": FORMAT, "backup_id": backup_id, "archive_sha256": digest, "files": files, "parts": parts}
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    size = sum((OUT_DIR / p["file"]).stat().st_size for p in parts)
    print(f"Backup {backup_id}: {files} files, {len(parts)} encrypted parts, {size / 1e6:.1f} MB in {OUT_DIR}")


def decrypt_to(target: Path) -> dict:
    manifest = json.loads((OUT_DIR / "manifest.json").read_text())
    if manifest.get("format") != FORMAT:
        sys.exit("Unknown backup format.")
    aead = AESGCM(load_key(create=False))
    digest = hashlib.sha256()
    with target.open("wb") as out:
        for index, part in enumerate(manifest["parts"]):
            sealed = (OUT_DIR / part["file"]).read_bytes()
            if hashlib.sha256(sealed).hexdigest() != part["sha256"]:
                sys.exit(f"{part['file']} is corrupt.")
            chunk = aead.decrypt(sealed[:12], sealed[12:], f"{manifest['backup_id']}:{index}".encode())
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest() != manifest["archive_sha256"]:
        sys.exit("Decrypted archive does not match the recorded checksum.")
    return manifest


def verify() -> None:
    with tempfile.TemporaryDirectory(prefix="careeros-verify-") as tmp:
        archive = Path(tmp) / "backup.tar.gz"
        manifest = decrypt_to(archive)
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            db = next((m for m in members if m.name == DATABASE), None)
            if db is not None:
                tar.extract(db, tmp, filter="data")
                with closing(sqlite3.connect(Path(tmp) / DATABASE)) as conn:
                    check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            else:
                check = "no database"
    print(f"Backup {manifest['backup_id']} decrypts: {len(members)} entries, database integrity: {check}")


def restore(destination: Path) -> None:
    if destination.exists() and any(destination.iterdir()):
        sys.exit(f"{destination} is not empty. Restore into an empty folder, then copy what you need.")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="careeros-restore-") as tmp:
        archive = Path(tmp) / "backup.tar.gz"
        manifest = decrypt_to(archive)
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(destination, filter="data")
    print(f"Restored backup {manifest['backup_id']} into {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup")
    sub.add_parser("verify")
    restore_cmd = sub.add_parser("restore")
    restore_cmd.add_argument("--to", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "backup":
        backup()
    elif args.command == "verify":
        verify()
    else:
        restore(args.to)


if __name__ == "__main__":
    main()
