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
