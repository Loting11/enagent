import base64
import hashlib
import hmac
import json
import os
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WeComError(RuntimeError):
    pass


class WeComCrypto:
    """Enterprise WeChat callback signature and AES-CBC codec."""

    def __init__(self, token, encoding_aes_key, receive_id):
        if not token:
            raise ValueError("缺少回调 Token")
        if len(encoding_aes_key) != 43:
            raise ValueError("EncodingAESKey 应为 43 个字符")
        self.token = token
        self.receive_id = receive_id
        try:
            self.key = base64.b64decode(encoding_aes_key + "=", validate=True)
        except ValueError as exc:
            raise ValueError("EncodingAESKey 格式不正确") from exc
        if len(self.key) != 32:
            raise ValueError("EncodingAESKey 解码后长度不正确")
        self.iv = self.key[:16]

    def signature(self, timestamp, nonce, encrypted):
        values = sorted([self.token, str(timestamp), str(nonce), encrypted])
        return hashlib.sha1("".join(values).encode("utf-8")).hexdigest()

    def verify(self, signature, timestamp, nonce, encrypted):
        expected = self.signature(timestamp, nonce, encrypted)
        if not signature or not hmac.compare_digest(signature, expected):
            raise WeComError("企微消息签名校验失败")

    def decrypt(self, encrypted):
        try:
            ciphertext = base64.b64decode(encrypted, validate=True)
            decryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            unpadder = padding.PKCS7(256).unpadder()
            plain = unpadder.update(padded) + unpadder.finalize()
            if len(plain) < 20:
                raise ValueError("message too short")
            length = struct.unpack("!I", plain[16:20])[0]
            message = plain[20 : 20 + length]
            receive_id = plain[20 + length :].decode("utf-8")
        except Exception as exc:
            raise WeComError("企微消息解密失败") from exc
        if self.receive_id and receive_id != self.receive_id:
            raise WeComError("企微消息接收方不匹配")
        return message.decode("utf-8")

    def encrypt(self, message, timestamp=None, nonce=None):
        timestamp = str(timestamp or int(time.time()))
        nonce = str(nonce or int.from_bytes(os.urandom(8), "big"))
        data = message.encode("utf-8")
        plain = os.urandom(16) + struct.pack("!I", len(data)) + data + self.receive_id.encode("utf-8")
        padder = padding.PKCS7(256).padder()
        padded = padder.update(plain) + padder.finalize()
        encryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).encryptor()
        encrypted = base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("ascii")
        return {
            "encrypt": encrypted,
            "signature": self.signature(timestamp, nonce, encrypted),
            "timestamp": timestamp,
            "nonce": nonce,
        }


class WeComClient:
    API_ROOT = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, timeout=None):
        self.timeout = timeout or int(os.getenv("WECOM_API_TIMEOUT", "10"))
        self._token = None
        self._token_expires_at = 0
        self._lock = threading.Lock()

    @property
    def configured(self):
        return all(
            os.getenv(key, "")
            for key in ("WECOM_CORP_ID", "WECOM_AGENT_ID", "WECOM_SECRET")
        )

    def _request_json(self, url, payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise WeComError("企业微信接口连接失败") from exc
        if result.get("errcode", 0) != 0:
            raise WeComError(
                f"企业微信接口错误 {result.get('errcode')}: {result.get('errmsg', 'unknown')}"
            )
        return result

    def access_token(self, force=False):
        with self._lock:
            if not force and self._token and time.time() < self._token_expires_at:
                return self._token
            if not self.configured:
                raise WeComError("企业微信应用配置不完整")
            query = urllib.parse.urlencode(
                {
                    "corpid": os.getenv("WECOM_CORP_ID"),
                    "corpsecret": os.getenv("WECOM_SECRET"),
                }
            )
            result = self._request_json(f"{self.API_ROOT}/gettoken?{query}")
            self._token = result["access_token"]
            self._token_expires_at = time.time() + int(result.get("expires_in", 7200)) - 120
            return self._token

    def send_text(self, user_id, text):
        if not user_id:
            raise WeComError("缺少企微成员 UserID")
        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": int(os.getenv("WECOM_AGENT_ID", "0")),
            "text": {"content": text},
            "safe": 0,
            "enable_duplicate_check": 1,
            "duplicate_check_interval": 1800,
        }
        token = self.access_token()
        url = f"{self.API_ROOT}/message/send?access_token={urllib.parse.quote(token)}"
        result = self._request_json(url, payload)
        if result.get("invaliduser"):
            raise WeComError(f"无效企微成员: {result['invaliduser']}")
        return result


def parse_encrypted_xml(body):
    try:
        root = ET.fromstring(body)
        encrypted = root.findtext("Encrypt", "")
    except ET.ParseError as exc:
        raise WeComError("企微回调 XML 格式错误") from exc
    if not encrypted:
        raise WeComError("企微回调缺少 Encrypt")
    return encrypted


def parse_message_xml(body):
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise WeComError("企微消息 XML 格式错误") from exc
    return {child.tag: child.text or "" for child in root}
