"""超星登录使用的 AES-CBC 协议。"""

import base64

import pyaes


def encrypt_login(value: str) -> str:
    key = b"u2oh6Vu^HWe4_AES"
    raw = value.encode("utf-8")
    padding = 16 - len(raw) % 16
    padded = raw + bytes([padding]) * padding
    cipher = pyaes.AESModeOfOperationCBC(key, iv=key)
    encrypted = b"".join(
        cipher.encrypt(padded[index : index + 16]) for index in range(0, len(padded), 16)
    )
    return base64.b64encode(encrypted).decode("ascii")
