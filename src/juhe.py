import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://chat-api.juhebot.com/open/GuidRequest"


class JuheError(Exception):
    pass


class JuheClient:
    """Small adapter for the supplier's virtual WeCom client API."""

    def __init__(self, api_url=None, app_key=None, app_secret=None, guid=None):
        self.api_url = api_url or os.getenv("JUHE_API_URL", DEFAULT_API_URL)
        self.app_key = app_key if app_key is not None else os.getenv("JUHE_APP_KEY", "")
        self.app_secret = (
            app_secret if app_secret is not None else os.getenv("JUHE_APP_SECRET", "")
        )
        self.guid = guid if guid is not None else os.getenv("JUHE_GUID", "")

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

    def send_text(self, conversation_id, content):
        conversation_id = str(conversation_id).strip()
        if not conversation_id.startswith(("S:", "R:")):
            conversation_id = f"S:{conversation_id}"
        return self.request(
            "/msg/send_text",
            {"conversation_id": conversation_id, "content": str(content)},
        )

    def get_profile(self):
        return self.request("/user/get_profile")

    def set_notify_url(self, notify_url):
        if not str(notify_url).startswith("https://"):
            raise JuheError("回调地址必须使用 HTTPS")
        return self.request("/client/set_notify_url", {"notify_url": str(notify_url)})


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
    return "juhe:{}:{}:{}".format(
        guid, data.get("id", ""), data.get("seq", data.get("sendtime", ""))
    )
