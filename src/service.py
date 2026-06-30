import json
from datetime import date


WELCOME = """你好，我是你的 AI 英语知识助手 👋

每天我会给你发送一个 AI 行业常用英语知识点。
回复「开始」即可订阅；回复「暂停」可以暂停推送。"""

AUTO_SUBSCRIBE_WELCOME = """你好，我是你的 AI 英语知识助手 👋

你已成功订阅「AI 行业常用英语」，我会每天发送一个知识点和一道小测试。
回复「来一个」立即体验；回复「暂停」可随时暂停。"""

OPENCLAW_REVIEW_REPLY = """已收到你的学习助手申请。

管理员审核通过后，我会开始发送 AI 行业英语知识点。"""

OPENCLAW_APPROVED_REPLY = """审核已通过，欢迎加入「AI 行业常用英语」。

回复「来一个」立即体验；回复「暂停」可随时暂停。"""


def format_learning_push(content):
    options = json.loads(content["options_json"])
    return (
        "今日 AI 英语\n"
        f"{content['term']}\n\n"
        "含义\n"
        f"{content['meaning']}\n\n"
        "说明\n"
        f"{content['explanation']}\n\n"
        "例句\n"
        f"{content['example_en']}\n"
        f"{content['example_cn']}\n\n"
        "小测试\n"
        f"{content['question']}\n\n"
        + "\n\n".join(options)
        + "\n\n回复 A / B / C 即可"
    )


class EnglishAgentService:
    def __init__(self, db, channel, agent):
        self.db = db
        self.channel = channel
        self.agent = agent

    def create_user(self, name, channel_user_id):
        user_id = self.db.execute(
            "INSERT INTO users (name, channel_user_id) VALUES (?, ?)",
            (name.strip() or "新用户", channel_user_id.strip()),
        )
        user = self.get_user(user_id)
        self.channel.send_text(user, WELCOME)
        return self.get_user(user_id)

    def get_user(self, user_id):
        return self.db.one("SELECT * FROM users WHERE id = ?", (user_id,))

    def get_user_by_channel_id(self, channel_user_id):
        return self.db.one(
            "SELECT * FROM users WHERE channel_user_id = ?", (channel_user_id,)
        )

    def auto_subscribe_contact(self, name, channel_user_id):
        existing = self.get_user_by_channel_id(channel_user_id)
        if existing:
            return existing, False
        try:
            user_id = self.db.execute(
                "INSERT INTO users (name, channel_user_id, subscription_status) VALUES (?, ?, 'active')",
                ((name or "微信用户").strip(), channel_user_id.strip()),
            )
        except Exception:
            existing = self.get_user_by_channel_id(channel_user_id)
            if existing:
                return existing, False
            raise
        user = self.get_user(user_id)
        self.channel.send_text(user, AUTO_SUBSCRIBE_WELCOME)
        return self.get_user(user_id), True

    def receive_from_channel(self, channel_user_id, text, name=None):
        user = self.get_user_by_channel_id(channel_user_id)
        if not user:
            user_id = self.db.execute(
                "INSERT INTO users (name, channel_user_id) VALUES (?, ?)",
                ((name or channel_user_id).strip(), channel_user_id.strip()),
            )
            user = self.get_user(user_id)
        return self.receive(user["id"], text)

    def users(self):
        return self.db.all("SELECT * FROM users ORDER BY id DESC")

    def approve_user(self, user_id):
        user = self.get_user(user_id)
        if not user:
            raise ValueError("用户不存在")
        self.db.execute(
            "UPDATE users SET subscription_status = 'active' WHERE id = ?", (user_id,)
        )
        user = self.get_user(user_id)
        self.channel.send_text(user, OPENCLAW_APPROVED_REPLY)
        return user

    def reject_user(self, user_id):
        user = self.get_user(user_id)
        if not user:
            raise ValueError("用户不存在")
        self.db.execute(
            "UPDATE users SET subscription_status = 'unsubscribed' WHERE id = ?",
            (user_id,),
        )
        user = self.get_user(user_id)
        self.channel.send_text(user, "你的申请暂未通过。如需重新申请，请联系管理员。")
        return user

    def messages(self, user_id):
        return self.db.all(
            "SELECT * FROM messages WHERE user_id = ? ORDER BY id ASC", (user_id,)
        )

    def receive(self, user_id, text):
        user = self.get_user(user_id)
        if not user:
            raise ValueError("用户不存在")
        text = text.strip()
        self.db.execute(
            "INSERT INTO messages (user_id, direction, text, kind) VALUES (?, 'in', ?, 'text')",
            (user_id, text),
        )

        if user["channel_user_id"].startswith("openclaw:") and user["subscription_status"] == "pending":
            self.channel.send_text(user, OPENCLAW_REVIEW_REPLY)
            return OPENCLAW_REVIEW_REPLY

        commands = {
            "开始": ("active", "订阅成功！从今天起，我会每天给你发送一个 AI 英语知识点。"),
            "订阅": ("active", "订阅成功！回复「来一个」可以立即体验。"),
            "暂停": ("paused", "已经暂停每日推送。回复「恢复」即可继续。"),
            "恢复": ("active", "已经恢复每日推送。"),
            "退订": ("unsubscribed", "已经为你退订。以后回复「开始」可以重新订阅。"),
        }
        if text in commands:
            status, reply = commands[text]
            self.db.execute(
                "UPDATE users SET subscription_status = ? WHERE id = ?", (status, user_id)
            )
            self.channel.send_text(user, reply)
            return reply

        if text in ("来一个", "今日知识", "学习"):
            return self.push_one(user_id, force=True)

        if text in ("难一点", "简单一点"):
            delta = 1 if text == "难一点" else -1
            level = max(1, min(3, user["difficulty"] + delta))
            self.db.execute("UPDATE users SET difficulty = ? WHERE id = ?", (level, user_id))
            reply = f"好的，后续内容难度已调整为 {level} 级。"
            self.channel.send_text(user, reply)
            return reply

        if text.upper() in ("A", "B", "C") and user["current_content_id"]:
            return self._answer_question(user, text.upper())

        content = None
        if user["current_content_id"]:
            content = self.db.one("SELECT * FROM content_items WHERE id = ?", (user["current_content_id"],))
        reply = self.agent.answer(user, text, content)
        self.channel.send_text(user, reply)
        return reply

    def _answer_question(self, user, answer):
        content = self.db.one("SELECT * FROM content_items WHERE id = ?", (user["current_content_id"],))
        correct = answer == content["answer"]
        self.db.execute(
            """INSERT INTO learning_events
            (user_id, content_id, event_type, answer, is_correct)
            VALUES (?, ?, 'answer', ?, ?)""",
            (user["id"], content["id"], answer, int(correct)),
        )
        if correct:
            streak = user["streak"] + 1
            self.db.execute("UPDATE users SET streak = ? WHERE id = ?", (streak, user["id"]))
            reply = f"回答正确 ✅\n\n{content['explanation']}\n\n你已经连续答对 {streak} 题。"
        else:
            self.db.execute("UPDATE users SET streak = 0 WHERE id = ?", (user["id"],))
            reply = f"这次答案是 {content['answer']}。\n\n{content['explanation']}"
        self.channel.send_text(user, reply)
        return reply

    def _select_content(self, user):
        item = self.db.one(
            """SELECT c.* FROM content_items c
            WHERE c.enabled = 1 AND c.difficulty <= ?
              AND c.id NOT IN (
                SELECT content_id FROM learning_events
                WHERE user_id = ? AND event_type = 'push'
              )
            ORDER BY c.difficulty DESC, c.id ASC LIMIT 1""",
            (user["difficulty"], user["id"]),
        )
        if item:
            return item
        return self.db.one(
            "SELECT * FROM content_items WHERE enabled = 1 AND difficulty <= ? ORDER BY RANDOM() LIMIT 1",
            (user["difficulty"],),
        )

    def push_one(self, user_id, force=False):
        user = self.get_user(user_id)
        if not user:
            raise ValueError("用户不存在")
        if not force and user["subscription_status"] != "active":
            return None
        content = self._select_content(user)
        if not content:
            raise ValueError("没有可用知识点")
        message = format_learning_push(content)
        try:
            self.channel.send_text(user, message)
            self.db.execute(
                "INSERT INTO learning_events (user_id, content_id, event_type) VALUES (?, ?, 'push')",
                (user_id, content["id"]),
            )
            self.db.execute(
                "INSERT INTO push_jobs (user_id, content_id, status) VALUES (?, ?, 'sent')",
                (user_id, content["id"]),
            )
            self.db.execute(
                "UPDATE users SET current_content_id = ?, last_push_date = ? WHERE id = ?",
                (content["id"], date.today().isoformat(), user_id),
            )
            return message
        except Exception as exc:
            self.db.execute(
                "INSERT INTO push_jobs (user_id, content_id, status, error) VALUES (?, ?, 'failed', ?)",
                (user_id, content["id"], str(exc)),
            )
            raise

    def run_due_pushes(self, hour):
        today = date.today().isoformat()
        users = self.db.all(
            """SELECT * FROM users
            WHERE subscription_status = 'active' AND preferred_hour = ?
              AND (last_push_date IS NULL OR last_push_date != ?)""",
            (hour, today),
        )
        sent = 0
        for user in users:
            if self.push_one(user["id"]):
                sent += 1
        return sent

    def dashboard(self):
        return {
            "users": self.db.one("SELECT COUNT(*) AS value FROM users")["value"],
            "active": self.db.one("SELECT COUNT(*) AS value FROM users WHERE subscription_status = 'active'")["value"],
            "messages": self.db.one("SELECT COUNT(*) AS value FROM messages")["value"],
            "pushes": self.db.one("SELECT COUNT(*) AS value FROM push_jobs WHERE status = 'sent'")["value"],
            "model_configured": self.agent.configured,
        }
