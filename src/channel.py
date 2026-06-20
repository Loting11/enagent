try:
    from .wecom import WeComClient
except ImportError:  # Running as `python3 src/app.py`.
    from wecom import WeComClient


class ChannelAdapter:
    """Stable boundary for a real WeCom automation provider."""

    def send_text(self, user, text):
        raise NotImplementedError

    def send_link(self, user, title, url):
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

    def create_group(self, name):
        return {"ok": True, "group_id": f"mock:{name}"}

    def invite_to_group(self, group_id, user_ids):
        return {"ok": True, "group_id": group_id, "user_ids": user_ids}


class WeComChannel(MockWeComChannel):
    """Send real application messages for WeCom users, while retaining Demo users."""

    def __init__(self, db, client=None):
        super().__init__(db)
        self.client = client or WeComClient()

    def send_text(self, user, text):
        channel_user_id = user["channel_user_id"]
        is_demo = channel_user_id.startswith("wx_demo_") or channel_user_id.startswith("mock:")
        result = {"ok": True, "channel": "mock"}
        if self.client.configured and not is_demo:
            result = self.client.send_text(channel_user_id, text)
            result["channel"] = "wecom"
        self.db.execute(
            "INSERT INTO messages (user_id, direction, text, kind) VALUES (?, 'out', ?, 'text')",
            (user["id"], text),
        )
        return result
