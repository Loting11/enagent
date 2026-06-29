try:
    from .wecom import WeComClient
    from .juhe import JuheClient
    from .openclaw import OpenClawClient
except ImportError:  # Running as `python3 src/app.py`.
    from wecom import WeComClient
    from juhe import JuheClient
    from openclaw import OpenClawClient


class ChannelAdapter:
    """Stable boundary for a real WeCom automation provider."""

    def send_text(self, user, text):
        raise NotImplementedError

    def send_link(self, user, title, url):
        raise NotImplementedError

    def send_voice_url(self, user, url, duration_seconds, transcript=""):
        raise NotImplementedError

    def create_group(self, name):
        raise NotImplementedError

    def invite_to_group(self, group_id, user_ids):
        raise NotImplementedError


class MockWeComChannel(ChannelAdapter):
    def __init__(self, db):
        self.db = db

    def send_text(self, user, text):
        self.db.execute(
            "INSERT INTO messages (user_id, direction, text, kind) VALUES (?, 'out', ?, 'text')",
            (user["id"], text),
        )
        return {"ok": True, "channel": "mock"}

    def send_link(self, user, title, url):
        return self.send_text(user, f"{title}\n{url}")

    def send_voice_url(self, user, url, duration_seconds, transcript=""):
        self.db.execute(
            "INSERT INTO messages (user_id, direction, text, kind) VALUES (?, 'out', ?, 'voice')",
            (user["id"], transcript or "[语音消息]"),
        )
        return {"ok": True, "channel": "mock"}

    def create_group(self, name):
        return {"ok": True, "group_id": f"mock:{name}"}

    def invite_to_group(self, group_id, user_ids):
        return {"ok": True, "group_id": group_id, "user_ids": user_ids}


class WeComChannel(MockWeComChannel):
    """Send through the protocol provider, then official app API, with a demo fallback."""

    def __init__(self, db, client=None, juhe_client=None, openclaw_client=None):
        super().__init__(db)
        self.client = client or WeComClient()
        self.juhe_client = juhe_client or JuheClient()
        self.openclaw_client = openclaw_client or OpenClawClient()

    def send_text(self, user, text):
        channel_user_id = user["channel_user_id"]
        is_demo = channel_user_id.startswith("wx_demo_") or channel_user_id.startswith("mock:")
        result = {"ok": True, "channel": "mock"}
        if channel_user_id.startswith("openclaw:"):
            result = self.openclaw_client.send_text(channel_user_id.split(":", 1)[1], text)
            result["channel"] = "openclaw"
        elif self.juhe_client.configured and not is_demo:
            result = self.juhe_client.send_text(channel_user_id, text)
            result["channel"] = "juhe"
        elif self.client.configured and not is_demo:
            result = self.client.send_text(channel_user_id, text)
            result["channel"] = "wecom"
        self.db.execute(
            "INSERT INTO messages (user_id, direction, text, kind) VALUES (?, 'out', ?, 'text')",
            (user["id"], text),
        )
        return result

    def send_voice_url(self, user, url, duration_seconds, transcript=""):
        channel_user_id = user["channel_user_id"]
        is_demo = channel_user_id.startswith("wx_demo_") or channel_user_id.startswith("mock:")
        if self.juhe_client.configured and not is_demo:
            result = self.juhe_client.send_voice_url(channel_user_id, url, duration_seconds)
            result["channel"] = "juhe"
        elif is_demo:
            result = {"ok": True, "channel": "mock"}
        else:
            raise RuntimeError("当前渠道不支持语音消息")
        self.db.execute(
            "INSERT INTO messages (user_id, direction, text, kind) VALUES (?, 'out', ?, 'voice')",
            (user["id"], transcript or "[语音消息]"),
        )
        return result
