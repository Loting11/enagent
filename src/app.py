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
from urllib.parse import parse_qs, quote, urlparse

from agent import AgentService
from channel import WeComChannel
from content import DEMO_CONTENT
from db import Database
from openclaw import DEFAULT_CLI_PATH, OpenClawClient, OpenClawError, OpenClawLoginSession, cli_available, resolve_cli_path
from service import EnglishAgentService
from wecom import WeComCrypto, WeComError, parse_encrypted_xml, parse_message_xml
from juhe import DEFAULT_API_URL, JuheClient, JuheError, juhe_event_key, parse_juhe_callback


ROOT = Path(__file__).resolve().parent.parent
SESSION_COOKIE = "enagent_session"
SESSION_MAX_AGE = 60 * 60 * 12


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
openclaw_login_session = None
openclaw_login_lock = threading.Lock()
openclaw_last_login_output = ""

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

OPENCLAW_FIELDS = {
    "enabled": ("OPENCLAW_ENABLED", False),
    "cli_path": ("OPENCLAW_CLI_PATH", False),
    "channel": ("OPENCLAW_CHANNEL", False),
    "account_id": ("OPENCLAW_ACCOUNT_ID", False),
    "bot_name": ("OPENCLAW_BOT_NAME", False),
}

VOICE_FIELDS = {
    "enabled": ("TTS_ENABLED", False),
    "provider": ("TTS_PROVIDER", False),
    "api_base": ("TTS_API_BASE", False),
    "region": ("TTS_REGION", False),
    "model": ("TTS_MODEL", False),
    "voice_id": ("TTS_VOICE_ID", False),
    "accent": ("TTS_ACCENT", False),
    "gender": ("TTS_GENDER", False),
    "speed": ("TTS_SPEED", False),
    "pitch": ("TTS_PITCH", False),
    "instruction": ("TTS_INSTRUCTION", False),
    "content_scope": ("TTS_CONTENT_SCOPE", False),
    "api_key": ("TTS_API_KEY", True),
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


def voice_config():
    defaults = {
        "enabled": "false",
        "provider": "azure",
        "api_base": "",
        "region": "",
        "model": "",
        "voice_id": "",
        "accent": "en-US",
        "gender": "female",
        "speed": "1.0",
        "pitch": "0",
        "instruction": "清晰、自然、耐心，适合英语学习者跟读。",
        "content_scope": "term_example",
    }
    result = {}
    for field, (env_key, sensitive) in VOICE_FIELDS.items():
        value = os.getenv(env_key, defaults.get(field, ""))
        if sensitive:
            result[f"{field}_configured"] = bool(value)
        elif field == "enabled":
            result[field] = value.lower() in ("1", "true", "yes", "on")
        else:
            result[field] = value
    required = (result.get("provider"), result.get("voice_id"), result.get("api_key_configured"))
    result["model_ready"] = all(required)
    result["delivery_ready"] = result["enabled"] and result["model_ready"]
    return result


def save_voice_config(body, allow_sensitive):
    updates = {}
    for field, (env_key, sensitive) in VOICE_FIELDS.items():
        if field not in body or (sensitive and not allow_sensitive):
            continue
        value = body[field]
        if field == "enabled":
            enabled = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
            value = "true" if enabled else "false"
        else:
            value = " ".join(str(value).splitlines()).strip()
        updates[env_key] = value
        os.environ[env_key] = value
    if updates:
        save_env_updates(updates)
    return voice_config()


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


def openclaw_config(public_origin=""):
    defaults = {
        "enabled": "false",
        "cli_path": DEFAULT_CLI_PATH,
        "channel": "openclaw-weixin",
        "account_id": "",
        "bot_name": "AI 英语订阅助手",
    }
    result = {}
    for field, (env_key, _sensitive) in OPENCLAW_FIELDS.items():
        value = os.getenv(env_key, defaults.get(field, ""))
        if field == "enabled":
            result[field] = value.lower() in ("1", "true", "yes", "on")
        else:
            result[field] = value
    token = os.getenv("OPENCLAW_CALLBACK_TOKEN", "")
    result["callback_path"] = f"/openclaw/callback?token={token}" if token else "/openclaw/callback"
    result["callback_url"] = (public_origin.rstrip("/") + result["callback_path"]) if public_origin else result["callback_path"]
    result["callback_ready"] = bool(token)
    result["cli_path"] = resolve_cli_path(result["cli_path"])
    result["cli_ready"] = cli_available(result["cli_path"])
    result["send_ready"] = bool(result["enabled"] and result["cli_ready"] and result["account_id"])
    return result


def save_openclaw_config(values):
    updates = {}
    for field, (env_key, _sensitive) in OPENCLAW_FIELDS.items():
        if field not in values:
            continue
        value = values[field]
        if field == "enabled":
            enabled = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
            value = "true" if enabled else "false"
        else:
            value = " ".join(str(value).splitlines()).strip()
        updates[env_key] = value
    if not os.getenv("OPENCLAW_CALLBACK_TOKEN", ""):
        updates["OPENCLAW_CALLBACK_TOKEN"] = secrets.token_urlsafe(32)
    if updates:
        save_env_updates(updates)
    service.channel.openclaw_client = OpenClawClient()
    return openclaw_config()


def openclaw_login_start(account_id=""):
    global openclaw_login_session, openclaw_last_login_output
    client = OpenClawClient()
    with openclaw_login_lock:
        if openclaw_login_session and openclaw_login_session.running:
            pass
        else:
            openclaw_last_login_output = ""
            command = client.login_command(account_id=account_id)
            openclaw_login_session = OpenClawLoginSession(command)
    return openclaw_login_status()


def openclaw_login_status():
    global openclaw_last_login_output
    with openclaw_login_lock:
        session = openclaw_login_session
        if not session:
            return {"running": False, "output": openclaw_last_login_output, "returncode": None}
        output = session.read_available()
        if output:
            openclaw_last_login_output = output
        return {
            "running": session.running,
            "output": output or openclaw_last_login_output,
            "returncode": session.returncode,
            "started_at": session.started_at,
        }


def openclaw_login_stop():
    global openclaw_login_session, openclaw_last_login_output
    with openclaw_login_lock:
        if openclaw_login_session:
            openclaw_last_login_output = openclaw_login_session.read_available() or openclaw_last_login_output
            openclaw_login_session.stop()
        openclaw_login_session = None
    return {"running": False, "output": openclaw_last_login_output, "returncode": None}


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


def process_openclaw_message(event_key, sender, text, name=None):
    try:
        service.receive_from_channel(f"openclaw:{sender}", text, name=name)
        db.finish_callback_event(event_key)
    except Exception as exc:
        db.finish_callback_event(event_key, str(exc)[:500])
        print(f"OpenClaw callback processing error: {type(exc).__name__}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        message = fmt % args
        message = re.sub(r"([?&]token=)[^& ]+", r"\1[redacted]", message)
        print(f"[{self.log_date_time_string()}] {message}")

    def _json(self, data, status=200, headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _admin_credentials(self):
        return os.getenv("ADMIN_USERNAME", ""), os.getenv("ADMIN_PASSWORD", "")

    def _valid_admin_credentials(self, supplied_user, supplied_password):
        username = os.getenv("ADMIN_USERNAME", "")
        password = os.getenv("ADMIN_PASSWORD", "")
        if not username or not password:
            return False
        return hmac.compare_digest(supplied_user, username) and hmac.compare_digest(
            supplied_password, password
        )

    def _basic_authorized(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
            supplied_user, supplied_password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return False
        return self._valid_admin_credentials(supplied_user, supplied_password)

    def _session_secret(self):
        return os.getenv("SESSION_SECRET") or os.getenv("ADMIN_PASSWORD") or "english-agent-admin"

    def _session_signature(self, issued_at):
        username, _ = self._admin_credentials()
        payload = f"{username}:{issued_at}".encode("utf-8")
        return hmac.new(self._session_secret().encode("utf-8"), payload, hashlib.sha256).hexdigest()

    def _cookies(self):
        cookies = {}
        for part in self.headers.get("Cookie", "").split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            cookies[key] = value
        return cookies

    def _session_authorized(self):
        if not all(self._admin_credentials()):
            return False
        value = self._cookies().get(SESSION_COOKIE, "")
        try:
            issued_at, signature = value.split(".", 1)
            issued = int(issued_at)
        except (ValueError, TypeError):
            return False
        if time.time() - issued > SESSION_MAX_AGE:
            return False
        expected = self._session_signature(issued_at)
        return hmac.compare_digest(signature, expected)

    def _authorized(self):
        return self._session_authorized() or self._basic_authorized()

    def _cookie_security(self):
        secure = self._public_origin().startswith("https://")
        return "; Secure" if secure else ""

    def _login_cookie(self):
        issued_at = str(int(time.time()))
        value = f"{issued_at}.{self._session_signature(issued_at)}"
        return (
            f"{SESSION_COOKIE}={value}; Max-Age={SESSION_MAX_AGE}; Path=/; "
            f"HttpOnly; SameSite=Lax{self._cookie_security()}"
        )

    def _clear_login_cookie(self):
        return (
            f"{SESSION_COOKIE}=; Max-Age=0; Path=/; "
            f"HttpOnly; SameSite=Lax{self._cookie_security()}"
        )

    def _redirect(self, target):
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _require_auth(self):
        if self._authorized():
            return True
        if urlparse(self.path).path.startswith("/api/"):
            self._json({"error": "请先登录后台"}, 401)
        else:
            self._redirect(f"/login?next={quote(self.path or '/', safe='')}")
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

    def _openclaw_receive(self, query):
        expected_token = os.getenv("OPENCLAW_CALLBACK_TOKEN", "")
        supplied_token = query.get("token", [""])[0]
        if not expected_token or not hmac.compare_digest(supplied_token, expected_token):
            raise OpenClawError("OpenClaw 回调认证失败")
        payload = self._body()
        sender = str(payload.get("sender") or payload.get("from") or payload.get("target") or "").strip()
        text = str(payload.get("text") or payload.get("message") or "").strip()
        name = str(payload.get("name") or payload.get("display_name") or "微信用户").strip()
        message_id = str(payload.get("message_id") or payload.get("id") or "").strip()
        if not sender or not text:
            raise OpenClawError("OpenClaw 回调缺少 sender 或 text")
        event_key = "openclaw:{}:{}".format(
            sender,
            message_id or hashlib.sha256(f"{sender}:{text}:{time.time_ns()}".encode("utf-8")).hexdigest(),
        )
        if db.claim_callback_event(event_key):
            threading.Thread(
                target=process_openclaw_message,
                args=(event_key, sender, text, name),
                daemon=True,
            ).start()
        return {"code": 0, "message": "ok"}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                return self._json({"ok": True})
            if path in ("/login", "/login.html", "/login.css", "/login.js"):
                return self._static("/login.html" if path == "/login" else path)
            if path == "/api/session":
                if self._authorized():
                    return self._json({"authenticated": True})
                return self._json({"authenticated": False}, 401)
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
            if path == "/api/config/openclaw":
                return self._json(openclaw_config(self._public_origin()))
            if path == "/api/config/openclaw/status":
                return self._json({"ok": True, "output": OpenClawClient().status()})
            if path == "/api/config/openclaw/login":
                return self._json(openclaw_login_status())
            if path == "/api/config/voice":
                return self._json(voice_config())
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "users"] and parts[3] == "messages":
                return self._json(service.messages(int(parts[2])))
            return self._static(path)
        except WeComError as exc:
            return self._text(str(exc), 403)
        except JuheError as exc:
            return self._json({"error": str(exc)}, 403)
        except OpenClawError as exc:
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
            if path == "/openclaw/callback":
                return self._json(self._openclaw_receive(parse_qs(parsed.query)))
            if path == "/api/login":
                body = self._body()
                username = str(body.get("username", ""))
                password = str(body.get("password", ""))
                if not all(self._admin_credentials()):
                    return self._json({"error": "后台账号尚未配置"}, 503)
                if not self._valid_admin_credentials(username, password):
                    return self._json({"error": "账号或密码不正确"}, 401)
                return self._json({"ok": True}, headers={"Set-Cookie": self._login_cookie()})
            if path == "/api/logout":
                return self._json({"ok": True}, headers={"Set-Cookie": self._clear_login_cookie()})
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
            if path == "/api/config/openclaw":
                return self._json(save_openclaw_config(body))
            if path == "/api/config/openclaw/status":
                return self._json({"ok": True, "output": OpenClawClient().status()})
            if path == "/api/config/openclaw/login/start":
                return self._json(openclaw_login_start(body.get("account_id", "")))
            if path == "/api/config/openclaw/login/stop":
                return self._json(openclaw_login_stop())
            if path == "/api/config/voice":
                forwarded_proto = self.headers.get("X-Forwarded-Proto", "").lower()
                trust_proxy = os.getenv("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes")
                secure = isinstance(self.connection, ssl.SSLSocket) or (
                    trust_proxy and forwarded_proto == "https"
                )
                if "api_key" in body and not secure:
                    return self._json({"error": "当前连接不是 HTTPS，已拒绝保存语音密钥"}, 403)
                return self._json(save_voice_config(body, allow_sensitive=secure))
            if path == "/api/config/voice/test":
                config = voice_config()
                missing = []
                if not config.get("provider"):
                    missing.append("模型服务")
                if not config.get("voice_id"):
                    missing.append("音色 ID")
                if not config.get("api_key_configured"):
                    missing.append("API Key")
                if missing:
                    return self._json({"error": "请先配置：" + "、".join(missing)}, 400)
                return self._json({"ok": True, "message": "配置完整；接入密钥后可进行真实试听。"})
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
                        3,
                        "Hello. Welcome to your daily English practice.",
                    )
                    return self._json({"ok": True})
                if parts[3] == "approve":
                    return self._json(service.approve_user(user_id))
                if parts[3] == "reject":
                    return self._json(service.reject_user(user_id))
            return self._json({"error": "Not found"}, 404)
        except WeComError as exc:
            return self._text(str(exc), 403)
        except JuheError as exc:
            return self._json({"error": str(exc)}, 403)
        except OpenClawError as exc:
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
