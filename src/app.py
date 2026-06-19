import base64
import hmac
import json
import mimetypes
import os
import ssl
import threading
import time
import tempfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from agent import AgentService
from channel import MockWeComChannel
from content import DEMO_CONTENT
from db import Database
from service import EnglishAgentService


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
service = EnglishAgentService(db, MockWeComChannel(db), AgentService())

WECOM_FIELDS = {
    "corp_id": ("WECOM_CORP_ID", False),
    "agent_id": ("WECOM_AGENT_ID", False),
    "test_user_id": ("WECOM_TEST_USER_ID", False),
    "secret": ("WECOM_SECRET", True),
    "token": ("WECOM_TOKEN", True),
    "encoding_aes_key": ("WECOM_ENCODING_AES_KEY", True),
}


def wecom_config():
    result = {}
    for field, (env_key, sensitive) in WECOM_FIELDS.items():
        value = os.getenv(env_key, "")
        result[field] = "" if sensitive else value
        result[f"{field}_configured"] = bool(value)
    result["callback_path"] = "/wecom/callback"
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
    return wecom_config()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/health":
                return self._json({"ok": True})
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
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "users"] and parts[3] == "messages":
                return self._json(service.messages(int(parts[2])))
            return self._static(path)
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
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
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "users"]:
                user_id = int(parts[2])
                if parts[3] == "messages":
                    reply = service.receive(user_id, body.get("text", ""))
                    return self._json({"reply": reply})
                if parts[3] == "push":
                    message = service.push_one(user_id, force=True)
                    return self._json({"message": message})
            return self._json({"error": "Not found"}, 404)
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
