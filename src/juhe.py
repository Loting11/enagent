import json
import os
import hashlib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://chat-api.juhebot.com/open/GuidRequest"


class JuheError(Exception):
    pass


class JuheClient:
    """Small adapter for the supplier's virtual WeCom client API."""

    def __init__(self, api_url=None, app_key=None, app_secret=None, guid=None, private_cdn_url=None):
        self.api_url = api_url or os.getenv("JUHE_API_URL", DEFAULT_API_URL)
        self.app_key = app_key if app_key is not None else os.getenv("JUHE_APP_KEY", "")
        self.app_secret = (
            app_secret if app_secret is not None else os.getenv("JUHE_APP_SECRET", "")
        )
        self.guid = guid if guid is not None else os.getenv("JUHE_GUID", "")
        self.private_cdn_url = (
            private_cdn_url
            if private_cdn_url is not None
            else os.getenv("JUHE_PRIVATE_CDN_URL", "")
        ).rstrip("/")

    @property
    def configured(self):
        return bool(
            self.api_url.startswith("https://")
            and self.app_key
            and self.app_secret
            and self.guid
        )

    def request(self, path, data=None, timeout=20):
        if not self.configured:
            raise JuheError("聚合聊天配置尚未完成")
        payload = {
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "path": path,
            "data": {"guid": self.guid, **(data or {})},
        }
        request = Request(
            self.api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as exc:
            raise JuheError(f"聚合聊天接口返回 HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise JuheError("聚合聊天接口连接失败") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JuheError("聚合聊天接口返回了无效数据") from exc

        code = result.get(
            "code", result.get("err_code", result.get("error_code", 0))
        )
        if code not in (0, "0", None):
            message = (
                result.get("message")
                or result.get("err_msg")
                or result.get("error_message")
                or "未知错误"
            )
            raise JuheError(f"聚合聊天接口错误：{message}")
        return result

    def request_private(self, path, data=None, timeout=60):
        if not self.private_cdn_url.startswith(("http://", "https://")):
            raise JuheError("聚合聊天私有 CDN 地址尚未配置")
        request = Request(
            self.private_cdn_url + "/" + str(path).lstrip("/"),
            data=json.dumps(data or {}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as exc:
            raise JuheError(f"聚合聊天私有 CDN 返回 HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise JuheError("聚合聊天私有 CDN 连接失败") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JuheError("聚合聊天私有 CDN 返回了无效数据") from exc
        code = result.get("code", result.get("err_code", result.get("error_code", 0)))
        if code not in (0, "0", None):
            message = result.get("message") or result.get("err_msg") or result.get("error_message") or "未知错误"
            raise JuheError(f"聚合聊天私有 CDN 错误：{message}")
        return result

    def send_text(self, conversation_id, content):
        conversation_id = self._conversation_id(conversation_id)
        return self.request(
            "/msg/send_text",
            {"conversation_id": conversation_id, "content": str(content)},
        )

    @staticmethod
    def _conversation_id(conversation_id):
        conversation_id = str(conversation_id).strip()
        if not conversation_id.startswith(("S:", "R:")):
            conversation_id = f"S:{conversation_id}"
        return conversation_id

    @staticmethod
    def _required(data, *names):
        for name in names:
            value = data.get(name)
            if value not in (None, ""):
                return value
        raise JuheError(f"聚合聊天媒体上传缺少字段：{'/'.join(names)}")

    def get_cdn_info(self):
        return self.request("/cdn/get_cdn_info")

    def upload_c2c(self, file_url, file_type=5):
        if not str(file_url).startswith("https://"):
            raise JuheError("语音文件必须使用公网 HTTPS 地址")
        cdn_result = self.get_cdn_info()
        cdn_data = cdn_result.get("data") or {}
        if not isinstance(cdn_data, dict):
            raise JuheError("聚合聊天 CDN 信息格式错误")
        base_request = {
            "cdn_dns": self._required(cdn_data, "cdn_dns"),
            "client_version": self._required(cdn_data, "client_version"),
            "corp_id": self._required(cdn_data, "corp_id"),
            "vid": self._required(cdn_data, "vid"),
        }
        payload = {"base_request": base_request, "file_type": int(file_type), "url": str(file_url)}
        if self.private_cdn_url:
            return self.request_private("/cloud/c2c_upload", payload, timeout=60)
        return self.request("/cloud/c2c_upload", payload, timeout=60)

    def send_voice_url(self, conversation_id, file_url, voice_time_seconds):
        upload_result = self.upload_c2c(file_url, file_type=5)
        upload_data = upload_result.get("data") or {}
        if not isinstance(upload_data, dict):
            raise JuheError("聚合聊天语音上传结果格式错误")
        payload = {
            "conversation_id": self._conversation_id(conversation_id),
            "file_id": self._required(upload_data, "file_id"),
            "size": int(self._required(upload_data, "file_size", "size")),
            "voice_time": max(1, int(voice_time_seconds)),
            "aes_key": self._required(upload_data, "aes_key"),
            "md5": self._required(upload_data, "file_md5", "md5"),
        }
        return self.request("/msg/send_voice", payload)

    def get_profile(self):
        return self.request("/user/get_profile")

    def set_notify_url(self, notify_url):
        if not str(notify_url).startswith("https://"):
            raise JuheError("回调地址必须使用 HTTPS")
        return self.request("/client/set_notify_url", {"notify_url": str(notify_url)})

    def sync_contacts(self):
        result = self.request("/contact/sync_contact")
        data = result.get("data") or {}
        contacts = data.get("contact_list") or [] if isinstance(data, dict) else []
        if not isinstance(contacts, list):
            raise JuheError("聚合聊天联系人数据格式错误")
        return contacts


def parse_juhe_callback(payload):
    if not isinstance(payload, dict):
        raise JuheError("回调数据格式错误")
    notify_type = int(payload.get("notify_type") or 0)
    guid = str(payload.get("guid") or "")
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise JuheError("回调消息格式错误")
    return guid, notify_type, data


def juhe_event_key(guid, data):
    unique = data.get("appinfo") or data.get("msg_id")
    if unique:
        return f"juhe:{guid}:{unique}"
    event_id = data.get("id", "")
    sequence = data.get("seq", data.get("sendtime", ""))
    if event_id or sequence:
        return "juhe:{}:{}:{}".format(guid, event_id, sequence)
    digest = hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"juhe:{guid}:{digest}"
