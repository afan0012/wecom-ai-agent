import base64
import hashlib
import struct
from urllib.parse import unquote

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WeComCryptoError(ValueError):
    pass


class WeComCrypto:
    def __init__(self, token: str, encoding_aes_key: str, receive_id: str):
        if not (token and encoding_aes_key and receive_id):
            raise WeComCryptoError("企业微信回调密钥尚未完整配置")
        self.token = token
        self.key = base64.b64decode(encoding_aes_key + "=")
        if len(self.key) != 32:
            raise WeComCryptoError("EncodingAESKey 无效")
        self.receive_id = receive_id.encode()

    def verify_signature(self, signature: str, timestamp: str, nonce: str, encrypted: str) -> bool:
        values = sorted([self.token, timestamp, nonce, encrypted])
        digest = hashlib.sha1("".join(values).encode()).hexdigest()
        return digest == signature

    def decrypt(self, encrypted: str) -> str:
        raw = base64.b64decode(unquote(encrypted))
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16]))
        padded = cipher.decryptor().update(raw) + cipher.decryptor().finalize()
        padding = padded[-1]
        if padding < 1 or padding > 32:
            raise WeComCryptoError("消息填充无效")
        content = padded[:-padding]
        if len(content) < 20:
            raise WeComCryptoError("消息长度无效")
        message_length = struct.unpack("!I", content[16:20])[0]
        message_end = 20 + message_length
        message, receive_id = content[20:message_end], content[message_end:]
        if receive_id != self.receive_id:
            raise WeComCryptoError("消息接收方不匹配")
        return message.decode("utf-8")
