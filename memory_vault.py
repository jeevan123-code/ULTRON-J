"""
memory_vault.py — Encrypted Memory Layer for Ultron-J BEYOND JARVIS.

All Ultron-J memory is encrypted at rest using Fernet symmetric encryption.
Key is derived from a password or machine-unique hardware fingerprint.

Features:
- Transparent read/write: drop-in replacement for open(file, r/w)
- AES-128 CBC under the hood (Fernet from cryptography library)
- Key derivation: PBKDF2-HMAC-SHA256 (100k iterations)
- Hardware fingerprint key (no password to remember)
- Encrypted backup rotation
- Emergency plaintext export

Usage:
    vault = MemoryVault()
    vault.write_json("memory.json", data)
    data = vault.read_json("memory.json")

Or use module-level helpers:
    from memory_vault import vault_read, vault_write
"""

import base64
import hashlib
import json
import os
import platform
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
VAULT_DIR      = os.path.join(_BASE_DIR, "vault")
VAULT_KEY_FILE = os.path.join(_BASE_DIR, ".vault_key")
VAULT_LOCK     = threading.Lock()

os.makedirs(VAULT_DIR, exist_ok=True)

# ── Cryptography ───────────────────────────────────────────────────────────────
try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("[MemoryVault] !! cryptography not installed. Vault running in plaintext mode.")
    print("              Install: pip install cryptography")


# =============================================================================
# KEY MANAGEMENT
# =============================================================================

def _hardware_fingerprint() -> str:
    """Generate a machine-unique string from hardware IDs."""
    parts = []
    try:
        parts.append(str(uuid.getnode()))           # MAC address
        parts.append(platform.node())               # hostname
        parts.append(platform.machine())            # CPU arch
        if platform.system() == "Windows":
            import subprocess
            r = subprocess.check_output(
                "wmic csproduct get uuid", shell=True, text=True, timeout=5
            )
            parts.append(r.strip().split()[-1])
        elif platform.system() == "Linux":
            fp = Path("/etc/machine-id")
            if fp.exists():
                parts.append(fp.read_text().strip())
    except Exception:
        pass
    combined = "|".join(parts) or "ultron-j-default-key"
    return hashlib.sha256(combined.encode()).hexdigest()


def _derive_key(password: str, salt: bytes = None) -> tuple:
    """Derive Fernet key from password using PBKDF2."""
    if salt is None:
        salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    key_bytes = kdf.derive(password.encode())
    key = base64.urlsafe_b64encode(key_bytes)
    return key, salt


def _load_or_create_key(password: str = None) -> "Fernet":
    """Load existing key or generate a new one."""
    if not CRYPTO_AVAILABLE:
        return None

    if os.path.exists(VAULT_KEY_FILE):
        try:
            with open(VAULT_KEY_FILE, "rb") as f:
                data = json.loads(f.read())
            salt = bytes.fromhex(data["salt"])
            pw   = password or _hardware_fingerprint()
            key, _ = _derive_key(pw, salt)
            return Fernet(key)
        except Exception:
            pass

    # Create new key
    pw   = password or _hardware_fingerprint()
    key, salt = _derive_key(pw)
    with open(VAULT_KEY_FILE, "wb") as f:
        f.write(json.dumps({
            "salt":       salt.hex(),
            "created_at": datetime.now().isoformat(),
            "note":       "Delete this file to reset encryption. All data will be lost."
        }).encode())
    return Fernet(key)


# =============================================================================
# VAULT CLASS
# =============================================================================

class MemoryVault:
    """
    Transparent encrypted file storage.
    Files are stored in vault/ as .enc files.
    Original paths are mapped via an index.
    """

    def __init__(self, password: str = None):
        self._fernet = _load_or_create_key(password) if CRYPTO_AVAILABLE else None
        self._index  = self._load_index()
        self._enabled = CRYPTO_AVAILABLE and self._fernet is not None

    def _load_index(self) -> Dict:
        idx_path = os.path.join(VAULT_DIR, "index.json")
        if os.path.exists(idx_path):
            try:
                with open(idx_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_index(self):
        idx_path = os.path.join(VAULT_DIR, "index.json")
        with open(idx_path, "w") as f:
            json.dump(self._index, f, indent=2)

    def _enc_path(self, logical_name: str) -> str:
        """Get the encrypted file path for a logical name."""
        if logical_name not in self._index:
            enc_name = hashlib.sha256(logical_name.encode()).hexdigest()[:16] + ".enc"
            self._index[logical_name] = enc_name
            self._save_index()
        return os.path.join(VAULT_DIR, self._index[logical_name])

    def write(self, logical_name: str, data: bytes):
        """Write encrypted data."""
        with VAULT_LOCK:
            if self._enabled:
                encrypted = self._fernet.encrypt(data)
                with open(self._enc_path(logical_name), "wb") as f:
                    f.write(encrypted)
            else:
                # Plaintext fallback
                path = os.path.join(_BASE_DIR, logical_name)
                with open(path, "wb") as f:
                    f.write(data)

    def read(self, logical_name: str) -> Optional[bytes]:
        """Read and decrypt data."""
        with VAULT_LOCK:
            if self._enabled:
                enc_path = self._enc_path(logical_name)
                if not os.path.exists(enc_path):
                    # Try reading plaintext original (migration)
                    plain_path = os.path.join(_BASE_DIR, logical_name)
                    if os.path.exists(plain_path):
                        with open(plain_path, "rb") as f:
                            data = f.read()
                        # Encrypt and store
                        self.write(logical_name, data)
                        return data
                    return None
                try:
                    with open(enc_path, "rb") as f:
                        return self._fernet.decrypt(f.read())
                except Exception:
                    return None
            else:
                path = os.path.join(_BASE_DIR, logical_name)
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        return f.read()
                return None

    def write_json(self, logical_name: str, data: Any):
        self.write(logical_name, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))

    def read_json(self, logical_name: str, default=None) -> Any:
        raw = self.read(logical_name)
        if raw is None:
            return default
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return default

    def exists(self, logical_name: str) -> bool:
        if self._enabled:
            return os.path.exists(self._enc_path(logical_name))
        return os.path.exists(os.path.join(_BASE_DIR, logical_name))

    def delete(self, logical_name: str):
        with VAULT_LOCK:
            if self._enabled:
                enc_path = self._enc_path(logical_name)
                if os.path.exists(enc_path):
                    os.remove(enc_path)
                if logical_name in self._index:
                    del self._index[logical_name]
                    self._save_index()
            else:
                path = os.path.join(_BASE_DIR, logical_name)
                if os.path.exists(path):
                    os.remove(path)

    def list_files(self) -> list:
        return list(self._index.keys())

    def backup(self, backup_dir: str = None):
        """Create a backup of the entire vault."""
        backup_dir = backup_dir or os.path.join(_BASE_DIR, "vault_backup")
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(backup_dir, f"vault_{ts}")
        shutil.copytree(VAULT_DIR, dest)
        return dest

    def export_plaintext(self, export_dir: str):
        """Emergency export — decrypt all files to plaintext."""
        os.makedirs(export_dir, exist_ok=True)
        exported = 0
        for logical_name in self._index:
            data = self.read(logical_name)
            if data:
                out_path = os.path.join(export_dir, logical_name.replace("/", "_"))
                with open(out_path, "wb") as f:
                    f.write(data)
                exported += 1
        return exported

    def get_status(self) -> dict:
        return {
            "encryption_enabled": self._enabled,
            "crypto_available":   CRYPTO_AVAILABLE,
            "vault_files":        len(self._index),
            "vault_dir":          VAULT_DIR,
        }

    def migrate_plaintext_files(self, files: list):
        """Migrate existing plaintext JSON files into vault."""
        migrated = []
        for fname in files:
            path = os.path.join(_BASE_DIR, fname)
            if os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                    self.write(fname, data)
                    # Rename original to .bak
                    os.rename(path, path + ".bak")
                    migrated.append(fname)
                except Exception as e:
                    print(f"[MemoryVault] Migration failed for {fname}: {e}")
        return migrated


# =============================================================================
# MODULE-LEVEL CONVENIENCE
# =============================================================================

_default_vault: Optional[MemoryVault] = None

def _get_vault() -> MemoryVault:
    global _default_vault
    if _default_vault is None:
        _default_vault = MemoryVault()
    return _default_vault


def vault_write(logical_name: str, data: Any):
    _get_vault().write_json(logical_name, data)


def vault_read(logical_name: str, default=None) -> Any:
    return _get_vault().read_json(logical_name, default)


def vault_exists(logical_name: str) -> bool:
    return _get_vault().exists(logical_name)


def vault_status() -> dict:
    return _get_vault().get_status()


def migrate_to_vault():
    """One-time migration of all Ultron-J plaintext files into vault."""
    files_to_migrate = [
        "memory.json", "improvements.json", "goals.json",
        "patterns.json", "episodic_memory.json", "entity_graph.json",
        "briefing.json", "tool_stats.json", "notes.json",
    ]
    migrated = _get_vault().migrate_plaintext_files(files_to_migrate)
    print(f"[MemoryVault] Migrated {len(migrated)} files: {migrated}")
    return migrated
