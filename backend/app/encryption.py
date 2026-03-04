import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = os.environ.get("LA_SECRET_KEY", "change-me")
    dk = hashlib.sha256(key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(dk))


def encrypt_token(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
