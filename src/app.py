import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import ssl
import secrets
import threading
import time
import tempfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from agent import AgentService
from channel import WeComChannel
from content import DEMO_CONTENT
from db import Database
from service import EnglishAgentService
from wecom import WeComCrypto, WeComError, parse_encrypted_xml, parse_message_xml
from juhe import DEFAULT_API_URL, JuheClient, JuheError, juhe_event_key, parse_juhe_callback


ROOT = Path(__file__).resolve().parent.parent


def load_env():
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env()
db_path = os.getenv("DB_PATH", str(ROOT / "data" / "english_agent.db"))
db = Database(db_path)
db.initialize(DEMO_CONTENT)
service = EnglishAgentService(db, WeComChannel(db), AgentService())

WECOM_FIELDS = {
    "corp_id": ("WECOM_CORP_ID", False),
    "agent_id": ("WECOM_AGENT_ID", False),
    "test_user_id": ("WECOM_TEST_USER_ID", False),
    "secret": ("WECOM_SECRET", True),
    "token": ("WECOM_TOKEN", True),
    "encoding_aes_key": ("WECOM_ENCODING_AES_KEY", True),
}

JUHE_FIELDS = {
    "api_url": ("JUHE_API_URL", False),
    "app_key": ("JUHE_APP_KEY", False),
    "guid": ("JUHE_GUID", False),
    "app_secret": ("JUHE_APP_SECRET", True),
    "private_cdn_url": ("JUHE_PRIVATE_CDN_URL", True),
}


def save_env_updates(updates):
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    output, handled = [], set()
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            handled.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in handled:
            output.append(f"{key}={value}")

    fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=ROOT)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(output) + "\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, env_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    for key, value in updates.items():
        os.environ[key] = value


def wecom_config():
    result = {}
    for field, (env_key, sensitive) in WECOM_FIELDS.items():
        value = os.getenv(env_key, "")
        result[field] = "" if sensitive else value
        result[f"{field}_configured"] = bool(value)
    result["callback_path"] = "/wecom/callback"
    result["callback_ready"] = all(
        os.getenv(key, "")
        for key in ("WECOM_CORP_ID", "WECOM_TOKEN", "WECOM_ENCODING_AES_KEY")
    )
    result["send_ready"] = all(
        os.getenv(key, "")
        for key in ("WECOM_CORP_ID", "WECOM_AGENT_ID", "WECOM_SECRET")
    )
    return result


def save_wecom_config(values, allow_sensitive=False):
    updates = {}
    for field, (env_key, sensitive) in WECOM_FIELDS.items():
        if field not in values:
            continue
        if sensitive and not allow_sensitive:
            raise ValueError("敏感配置只能通过 HTTPS 提交")
        value = str(values[field]).strip()
        if "\n" in value or "\r" in value:
            raise ValueError(f"{field} 不能包含换行")
        if field == "encoding_aes_key" and value and len(value) != 43:
            raise ValueError("EncodingAESKey 应为 43 个字符")
        updates[env_key] = value

    save_env_updates(updates)
    return wecom_config()


def juhe_config():
    result = {}
    for field, (env_key, sensitive) in JUHE_FIELDS.items():
        value = os.getenv(env_key, "")
        if field == "api_url" and not value:
            value = DEFAULT_API_URL
        result[field] = "" if sensitive else value
        result[f"{field}_configured"] = bool(value)
    token = os.getenv("JUHE_CALLBACK_TOKEN", "")
    result["callback_path"] = f"/juhe/callback?token={token}" if token else "/juhe/callback"
    result["callback_ready"] = bool(token and os.getenv("JUHE_GUID", ""))
    result["send_ready"] = all(
        os.getenv(key, "") for key in ("JUHE_APP_KEY", "JUHE_APP_SECRET", "JUHE_GUID")
    )
    result["voice_ready"] = result["send_ready"] and bool(
        os.getenv("JUHE_PRIVATE_CDN_URL", "")
    )
    return result


def save_juhe_config(values, allow_sensitive=False):
    updates = {}
    for field, (env_key, sensitive) in JUHE_FIELDS.items():
        if field not in values:
            continue
        if sensitive and not allow_sensitive:
            raise ValueError("敏感配置只能通过 HTTPS 提交")
        value = str(values[field]).strip()
        if "\n" in value or "\r" in value:
            raise ValueError(f"{field} 不能包含换行")
        if field == "api_url" and value and not value.startswith("https://"):
            raise ValueError("API 地址必须使用 HTTPS")
        if field == "private_cdn_url" and value and not value.startswith(("http://", "https://")):
            raise ValueError("私有 CDN 地址必须以 http:// 或 https:// 开头")
        updates[env_key] = value
    if not os.getenv("JUHE_CALLBACK_TOKEN", ""):
        updates["JUHE_CALLBACK_TOKEN"] = secrets.token_urlsafe(32)
    save_env_updates(updates)
    service.channel.juhe_client = JuheClient()
    return juhe_config()


def callback_crypto():
    try:
        return WeComCrypto(
            os.getenv("WECOM_TOKEN", ""),
            os.getenv("WECOM_ENCODING_AES_KEY", ""),
            os.getenv("WECOM_CORP_ID", ""),
        )
    except ValueError as exc:
        raise WeComError("企业微信回调配置尚未完成") from exc


def process_wecom_message(event_key, message):
    try:
        if message.get("MsgType") == "text" and message.get("Content", "").strip():
            service.receive_from_channel(
                message.get("FromUserName", ""), message["Content"].strip()
            )
        db.finish_callback_event(event_key)
    except Exception as exc:
        db.finish_callback_event(event_key, str(exc)[:500])
        print(f"WeCom callback processing error: {exc}")


def process_juhe_message(event_key, sender, text, name=None):
    try:
        service.receive_from_channel(sender, text, name=name)
        db.finish_callback_event(event_key)
    except Exception as exc:
        db.finish_callback_event(event_key, str(exc)[:500])
        print(f"Juhe callback processing error: {type(exc).__name__}")


def process_juhe_contact_change(event_key):
    try:
        contacts = service.channel.juhe_client.sync_contacts()
        added = db.record_channel_contacts(contacts)
        for contact in added:
            service.auto_subscribe_contact(contact["name"], contact["user_id"])
        db.finish_callback_event(event_key)
    except Exception as exc:
        db.finish_callback_event(event_key, str(exc)[:500])
        print(f"Juhe contact callback processing error: {type(exc).__name__}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        message = fmt % args
        message = re.sub(r"([?&]token=)[^& ]+", r"\1[redacted]", message)
        print(f"[{self.log_date_time_string()}] {message}")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        username = os.getenv("ADMIN_USERNAME", "")
        password = os.getenv("ADMIN_PASSWORD", "")
        if not username or not password:
            return False
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
            supplied_user, supplied_password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return False
        return hmac.compare_digest(supplied_user, username) and hmac.compare_digest(
            supplied_password, password
        )

    def _require_auth(self):
        if self._authorized():
            return True
        body = b"Authentication required"
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="English Agent Admin"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def _body(self):
        return json.loads(self._raw_body().decode("utf-8") or "{}")

    def _raw_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            raise ValueError("请求内容过大")
        return self.rfile.read(length)

    def _public_origin(self):
        configured = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
        if configured:
            return configured
        trust_proxy = os.getenv("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes")
        proto = self.headers.get("X-Forwarded-Proto", "") if trust_proxy else ""
        proto = proto or ("https" if isinstance(self.connection, ssl.SSLSocket) else "http")
        host = self.headers.get("Host", "")
        return f"{proto}://{host}".rstrip("/")

    def _wecom_verify(self, query):
        encrypted = query.get("echostr", [""])[0]
        signature = query.get("msg_signature", [""])[0]
        timestamp = query.get("timestamp", [""])[0]
        nonce = query.get("nonce", [""])[0]
        crypto = callback_crypto()
        crypto.verify(signature, timestamp, nonce, encrypted)
        return crypto.decrypt(encrypted)

    def _wecom_receive(self, query):
        encrypted = parse_encrypted_xml(self._raw_body())
        signature = query.get("msg_signature", [""])[0]
        timestamp = query.get("timestamp", [""])[0]
        nonce = query.get("nonce", [""])[0]
        crypto = callback_crypto()
        crypto.verify(signature, timestamp, nonce, encrypted)
        plain_xml = crypto.decrypt(encrypted)
        message = parse_message_xml(plain_xml)
        expected_agent = os.getenv("WECOM_AGENT_ID", "")
        if expected_agent and message.get("AgentID") and message["AgentID"] != expected_agent:
            raise WeComError("企微 AgentID 不匹配")
        if not message.get("FromUserName"):
            raise WeComError("企微消息缺少发送者")
        event_key = message.get("MsgId") or hashlib.sha256(plain_xml.encode("utf-8")).hexdigest()
        if db.claim_callback_event(event_key):
            threading.Thread(
                target=process_wecom_message, args=(event_key, message), daemon=True
            ).start()
        return "success"

    def _juhe_receive(self, query):
        expected_token = os.getenv("JUHE_CALLBACK_TOKEN", "")
        supplied_token = query.get("token", [""])[0]
        if not expected_token or not hmac.compare_digest(supplied_token, expected_token):
            raise JuheError("聚合聊天回调认证失败")
        payload = self._body()
        guid, notify_type, data = parse_juhe_callback(payload)
        expected_guid = os.getenv("JUHE_GUID", "")
        if not expected_guid or not hmac.compare_digest(guid, expected_guid):
            raise JuheError("聚合聊天实例不匹配")
        if notify_type == 2131:
            event_key = f"juhe-contact:{juhe_event_key(guid, data)}"
            if db.claim_callback_event(event_key):
                threading.Thread(
                    target=process_juhe_contact_change,
                    args=(event_key,),
                    daemon=True,
                ).start()
            return {"code": 0, "message": "ok"}
        if notify_type != 11010:
            return {"code": 0, "message": "ok"}
        if str(data.get("referid", "0")) not in ("", "0"):
            return {"code": 0, "message": "ok"}

        sender = str(data.get("sender") or data.get("from_id") or "").strip()
        room_id = str(data.get("roomid") or data.get("room_id") or "0").strip()
        text = str(data.get("content") or "").strip()
        content_type = data.get("content_type")
        msg_type = data.get("msg_type")
        is_text = (
            content_type in (2, "2")
            if content_type is not None
            else msg_type in (1, "1")
        )
        # Phase one is limited to personal-WeChat customers in direct chats. This
        # also prevents the employee's own outbound messages from looping back.
        is_external_customer = sender.startswith("788")
        if not (sender and text and is_text and is_external_customer and room_id in ("", "0")):
            return {"code": 0, "message": "ok"}

        event_key = juhe_event_key(guid, data)
        if db.claim_callback_event(event_key):
            threading.Thread(
                target=process_juhe_message,
                args=(event_key, sender, text, data.get("sender_name")),
                daemon=True,
            ).start()
        return {"code": 0, "message": "ok"}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                return self._json({"ok": True})
            if path in ("/audio/voice-test.m4a", "/audio/voice-test.silk"):
                return self._static(path)
            if path == "/wecom/callback":
                return self._text(self._wecom_verify(parse_qs(parsed.query)))
            if not self._require_auth():
                return
            if path == "/api/dashboard":
                return self._json(service.dashboard())
            if path == "/api/users":
                return self._json(service.users())
            if path == "/api/content":
                return self._json(db.all("SELECT * FROM content_items ORDER BY difficulty, id"))
            if path == "/api/config/wecom":
                return self._json(wecom_config())
            if path == "/api/config/juhe":
                return self._json(juhe_config())
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "users"] and parts[3] == "messages":
                return self._json(service.messages(int(parts[2])))
            return self._static(path)
        except WeComError as exc:
            return self._text(str(exc), 403)
        except JuheError as exc:
            return self._json({"error": str(exc)}, 403)
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/wecom/callback":
                return self._text(self._wecom_receive(parse_qs(parsed.query)))
            if path == "/juhe/callback":
                return self._json(self._juhe_receive(parse_qs(parsed.query)))
            if not self._require_auth():
                return
            body = self._body()
            if path == "/api/users":
                user = service.create_user(body.get("name", ""), body.get("channel_user_id", ""))
                return self._json(user, 201)
            if path == "/api/push/run":
                users = service.users()
                sent = 0
                for user in users:
                    if user["subscription_status"] == "active":
                        service.push_one(user["id"], force=True)
                        sent += 1
                return self._json({"sent": sent})
            if path == "/api/config/wecom/test":
                test_user = os.getenv("WECOM_TEST_USER_ID", "")
                if not test_user:
                    return self._json({"error": "请先填写测试员工 UserID"}, 400)
                service.channel.client.send_text(
                    test_user, "企业微信英语助手连接成功 ✅\n回复「开始」即可订阅。"
                )
                return self._json({"ok": True})
            if path == "/api/config/wecom":
                forwarded_proto = self.headers.get("X-Forwarded-Proto", "").lower()
                trust_proxy = os.getenv("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes")
                secure = isinstance(self.connection, ssl.SSLSocket) or (
                    trust_proxy and forwarded_proto == "https"
                )
                sensitive_present = any(
                    field in body for field, (_, sensitive) in WECOM_FIELDS.items() if sensitive
                )
                if sensitive_present and not secure:
                    return self._json({"error": "当前连接不是 HTTPS，已拒绝保存敏感配置"}, 403)
                return self._json(save_wecom_config(body, allow_sensitive=secure))
            if path == "/api/config/juhe/test":
                if not service.channel.juhe_client.configured:
                    return self._json({"error": "请先完成聚合聊天配置"}, 400)
                service.channel.juhe_client.get_profile()
                return self._json({"ok": True})
            if path == "/api/config/juhe/callback/register":
                if not service.channel.juhe_client.configured:
                    return self._json({"error": "请先完成聚合聊天配置"}, 400)
                callback_url = self._public_origin() + juhe_config()["callback_path"]
                service.channel.juhe_client.set_notify_url(callback_url)
                return self._json({"ok": True})
            if path == "/api/config/juhe/contacts/baseline":
                if not service.channel.juhe_client.configured:
                    return self._json({"error": "请先完成聚合聊天配置"}, 400)
                contacts = service.channel.juhe_client.sync_contacts()
                added = db.record_channel_contacts(contacts)
                return self._json({"ok": True, "recorded": len(added)})
            if path == "/api/config/juhe":
                forwarded_proto = self.headers.get("X-Forwarded-Proto", "").lower()
                trust_proxy = os.getenv("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes")
                secure = isinstance(self.connection, ssl.SSLSocket) or (
                    trust_proxy and forwarded_proto == "https"
                )
                sensitive_present = any(
                    field in body for field, (_, sensitive) in JUHE_FIELDS.items() if sensitive
                )
                if sensitive_present and not secure:
                    return self._json({"error": "当前连接不是 HTTPS，已拒绝保存敏感配置"}, 403)
                return self._json(save_juhe_config(body, allow_sensitive=secure))
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "users"]:
                user_id = int(parts[2])
                if parts[3] == "messages":
                    reply = service.receive(user_id, body.get("text", ""))
                    return self._json({"reply": reply})
                if parts[3] == "push":
                    message = service.push_one(user_id, force=True)
                    return self._json({"message": message})
                if parts[3] == "voice-test":
                    user = service.get_user(user_id)
                    if not user:
                        return self._json({"error": "用户不存在"}, 404)
                    voice_url = self._public_origin() + "/audio/voice-test.silk"
                    service.channel.send_voice_url(
                        user,
                        voice_url,
                        2876,
                        "Hello. Welcome to your daily English practice.",
                    )
                    return self._json({"ok": True})
            return self._json({"error": "Not found"}, 404)
        except WeComError as exc:
            return self._text(str(exc), 403)
        except JuheError as exc:
            return self._json({"error": str(exc)}, 403)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def _static(self, path):
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (ROOT / "static" / relative).resolve()
        static_root = (ROOT / "static").resolve()
        if static_root not in target.parents and target != static_root:
            return self._json({"error": "Not found"}, 404)
        if not target.exists() or not target.is_file():
            return self._json({"error": "Not found"}, 404)
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def scheduler_loop():
    last_hour = None
    while True:
        now = datetime.now()
        marker = now.strftime("%Y-%m-%d-%H")
        if marker != last_hour:
            try:
                service.run_due_pushes(now.hour)
            except Exception as exc:
                print(f"Scheduler error: {exc}")
            last_hour = marker
        time.sleep(60)


def main():
    port = int(os.getenv("PORT", "8080"))
    threading.Thread(target=scheduler_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"English Agent MVP running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
