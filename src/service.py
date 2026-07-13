import json
from datetime import date, timedelta


TRIAL_DAYS = 7

WELCOME = """你好，我是你的 Agent 服务助手 👋

管理员开通服务后，我会按你的订阅推送内容。
你可以回复「来一个英语」或「今日早报」体验已开通的服务。"""

AUTO_SUBSCRIBE_WELCOME = """你好，我是你的 AI 英语知识助手 👋

你已成功订阅「AI 行业常用英语」，我会每天发送一个知识点和一道小测试。
回复「来一个」立即体验；回复「暂停」可随时暂停。"""

OPENCLAW_REVIEW_REPLY = """已收到你的学习助手申请。

管理员审核通过后，我会开始发送 AI 行业英语知识点。"""

OPENCLAW_APPROVED_REPLY = """审核已通过，欢迎加入 Agent 服务。

管理员开通具体服务后，你可以回复「来一个英语」或「今日早报」体验。"""


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


def format_briefing_push(content):
    source = content.get("source_url") or ""
    source_block = f"\n\n来源\n{source}" if source else ""
    return (
        "AI 行业早报\n"
        f"{content['term']}\n\n"
        "摘要\n"
        f"{content['meaning']}\n\n"
        "解读\n"
        f"{content['explanation']}"
        f"{source_block}\n\n"
        "回复「今日早报」获取下一条，或回复「暂停早报」暂停。"
    )


def format_content_push(content):
    if content.get("product_key") == "ai_briefing" or content.get("content_type") == "briefing":
        return format_briefing_push(content)
    return format_learning_push(content)


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

    def products(self):
        return self.db.all("SELECT * FROM products ORDER BY id")

    def update_product(self, product_key, values):
        product = self.db.one("SELECT * FROM products WHERE product_key = ?", (product_key,))
        if not product:
            raise ValueError("产品不存在")
        allowed = {
            "name": str,
            "description": str,
            "default_push_hour": int,
            "payment_url": str,
            "enabled": int,
        }
        updates, params = [], []
        for field, caster in allowed.items():
            if field in values:
                updates.append(f"{field} = ?")
                params.append(caster(values[field]))
        if updates:
            params.append(product_key)
            self.db.execute(
                f"UPDATE products SET {', '.join(updates)} WHERE product_key = ?",
                tuple(params),
            )
        return self.db.one("SELECT * FROM products WHERE product_key = ?", (product_key,))

    def content_items(self):
        return self.db.all(
            """SELECT c.*, p.name AS product_name
            FROM content_items c
            LEFT JOIN products p ON p.product_key = c.product_key
            ORDER BY c.product_key, c.review_status, c.difficulty, c.id"""
        )

    def save_content_item(self, values, content_id=None):
        product_key = str(values.get("product_key") or "ai_english").strip()
        if not self.db.one("SELECT * FROM products WHERE product_key = ?", (product_key,)):
            raise ValueError("产品不存在")
        options = values.get("options")
        if isinstance(options, str):
            options = [line.strip() for line in options.splitlines() if line.strip()]
        if not options:
            options = ["A. 已理解", "B. 不确定", "C. 稍后再看"]
        payload = {
            "term": str(values.get("term") or "").strip(),
            "meaning": str(values.get("meaning") or "").strip(),
            "explanation": str(values.get("explanation") or "").strip(),
            "example_en": str(values.get("example_en") or "").strip(),
            "example_cn": str(values.get("example_cn") or "").strip(),
            "question": str(values.get("question") or "这条内容最核心的信息是什么？").strip(),
            "options_json": json.dumps(options, ensure_ascii=False),
            "answer": str(values.get("answer") or "A").strip().upper(),
            "difficulty": int(values.get("difficulty") or 1),
            "topic": str(values.get("topic") or "General").strip(),
            "enabled": 1 if str(values.get("enabled", 1)).lower() in ("1", "true", "yes") else 0,
            "product_key": product_key,
            "content_type": str(values.get("content_type") or "knowledge_card").strip(),
            "review_status": str(values.get("review_status") or "pending").strip(),
            "source_url": str(values.get("source_url") or "").strip(),
            "image_url": str(values.get("image_url") or "").strip(),
        }
        if not payload["term"] or not payload["meaning"]:
            raise ValueError("标题和摘要不能为空")
        if content_id:
            fields = ", ".join(f"{key} = ?" for key in payload)
            self.db.execute(
                f"UPDATE content_items SET {fields} WHERE id = ?",
                tuple(payload.values()) + (content_id,),
            )
            return self.db.one("SELECT * FROM content_items WHERE id = ?", (content_id,))
        new_id = self.db.execute(
            """INSERT INTO content_items
            (term, meaning, explanation, example_en, example_cn, question, options_json,
             answer, difficulty, topic, enabled, product_key, content_type, review_status,
             source_url, image_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(payload.values()),
        )
        return self.db.one("SELECT * FROM content_items WHERE id = ?", (new_id,))

    def subscriptions(self, user_id):
        return self.db.all(
            """SELECT s.*, p.name AS product_name, p.description AS product_description,
                      p.payment_url
            FROM user_subscriptions s
            LEFT JOIN products p ON p.product_key = s.product_key
            WHERE s.user_id = ?
            ORDER BY p.id, s.id""",
            (user_id,),
        )

    def open_trial_subscription(self, user_id, product_key, days=TRIAL_DAYS):
        user = self.get_user(user_id)
        product = self.db.one("SELECT * FROM products WHERE product_key = ?", (product_key,))
        if not user:
            raise ValueError("用户不存在")
        if not product:
            raise ValueError("产品不存在")
        trial_ends_at = (date.today() + timedelta(days=int(days))).isoformat()
        self.db.execute(
            """INSERT INTO user_subscriptions
            (user_id, product_key, status, preferred_hour, trial_ends_at)
            VALUES (?, ?, 'trial', ?, ?)
            ON CONFLICT(user_id, product_key) DO UPDATE SET
              status = 'trial',
              preferred_hour = excluded.preferred_hour,
              trial_ends_at = excluded.trial_ends_at""",
            (user_id, product_key, product["default_push_hour"], trial_ends_at),
        )
        self.db.execute(
            "UPDATE users SET subscription_status = 'active' WHERE id = ?", (user_id,)
        )
        return self.subscription(user_id, product_key)

    def subscription(self, user_id, product_key):
        return self.db.one(
            "SELECT * FROM user_subscriptions WHERE user_id = ? AND product_key = ?",
            (user_id, product_key),
        )

    def update_subscription(self, user_id, product_key, values):
        subscription = self.subscription(user_id, product_key)
        if not subscription:
            raise ValueError("订阅不存在")
        allowed = {
            "status": str,
            "preferred_hour": int,
            "trial_ends_at": str,
            "paid_until": str,
        }
        updates, params = [], []
        for field, caster in allowed.items():
            if field in values:
                value = values[field]
                if value is None:
                    value = ""
                updates.append(f"{field} = ?")
                params.append(caster(value) if value != "" else None)
        if updates:
            params.extend([user_id, product_key])
            self.db.execute(
                f"UPDATE user_subscriptions SET {', '.join(updates)} WHERE user_id = ? AND product_key = ?",
                tuple(params),
            )
        return self.subscription(user_id, product_key)

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

    def _notify_best_effort(self, user, text):
        try:
            self.channel.send_text(user, text)
            return None
        except Exception as exc:
            self.db.execute(
                "INSERT INTO messages (user_id, direction, text, kind) VALUES (?, 'out', ?, 'text')",
                (user["id"], f"通知发送失败：{str(exc)[:300]}"),
            )
            return f"用户状态已更新，但通知发送失败：{str(exc)[:120]}"

    def approve_user(self, user_id):
        user = self.get_user(user_id)
        if not user:
            raise ValueError("用户不存在")
        self.db.execute(
            "UPDATE users SET subscription_status = 'active' WHERE id = ?", (user_id,)
        )
        user = self.get_user(user_id)
        warning = self._notify_best_effort(user, OPENCLAW_APPROVED_REPLY)
        if warning:
            user["warning"] = warning
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
        warning = self._notify_best_effort(user, "你的申请暂未通过。如需重新申请，请联系管理员。")
        if warning:
            user["warning"] = warning
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

        normalized = text.lower().replace(" ", "")
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

        product_key = self._product_key_from_text(normalized, user)
        push_intents = (
            "来一个",
            "今日知识",
            "学习",
            "再来一个",
            "再推一个",
            "给我推一个",
            "下一个",
            "换一个",
            "新的",
            "这个推过了",
            "今日早报",
            "早报",
        )
        if text in push_intents or any(intent in normalized for intent in push_intents):
            return self.push_one(user_id, force=True, product_key=product_key)

        if normalized in ("暂停早报", "暂停行业早报"):
            return self._set_product_status(user_id, "ai_briefing", "paused", "已暂停 AI 行业早报。")
        if normalized in ("暂停英语", "暂停英文"):
            return self._set_product_status(user_id, "ai_english", "paused", "已暂停 AI 英语学习。")

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

    def _product_key_from_text(self, normalized_text, user):
        if "早报" in normalized_text or "资讯" in normalized_text or "新闻" in normalized_text:
            return "ai_briefing"
        if "英语" in normalized_text or "英文" in normalized_text or "单词" in normalized_text:
            return "ai_english"
        if user.get("current_content_id"):
            content = self.db.one("SELECT product_key FROM content_items WHERE id = ?", (user["current_content_id"],))
            if content:
                return content["product_key"]
        subscriptions = self.subscriptions(user["id"])
        if len(subscriptions) == 1:
            return subscriptions[0]["product_key"]
        return "ai_english"

    def _set_product_status(self, user_id, product_key, status, reply):
        if not self.subscription(user_id, product_key):
            reply = "你还没有开通这个服务，请联系管理员开通。"
        else:
            self.update_subscription(user_id, product_key, {"status": status})
        user = self.get_user(user_id)
        self.channel.send_text(user, reply)
        return reply

    def _subscription_can_receive(self, subscription):
        if not subscription:
            return False
        if subscription["status"] not in ("trial", "paid", "active"):
            return False
        today = date.today().isoformat()
        if subscription["status"] == "trial" and subscription.get("trial_ends_at") and subscription["trial_ends_at"] < today:
            return False
        if subscription["status"] == "paid" and subscription.get("paid_until") and subscription["paid_until"] < today:
            return False
        return True

    def _ensure_legacy_subscription(self, user, product_key):
        subscription = self.subscription(user["id"], product_key)
        if subscription:
            return subscription
        if product_key == "ai_english" and user["subscription_status"] == "active":
            return self.open_trial_subscription(user["id"], "ai_english")
        return None

    def _select_content(self, user, product_key):
        item = self.db.one(
            """SELECT c.* FROM content_items c
            WHERE c.enabled = 1
              AND c.product_key = ?
              AND c.review_status = 'approved'
              AND c.difficulty <= ?
              AND c.id NOT IN (
                SELECT content_id FROM learning_events
                WHERE user_id = ? AND event_type = 'push'
              )
            ORDER BY c.difficulty DESC, c.id ASC LIMIT 1""",
            (product_key, user["difficulty"], user["id"]),
        )
        if item:
            return item
        return self.db.one(
            """SELECT * FROM content_items
            WHERE enabled = 1 AND product_key = ? AND review_status = 'approved'
              AND difficulty <= ?
            ORDER BY RANDOM() LIMIT 1""",
            (product_key, user["difficulty"]),
        )

    def push_one(self, user_id, force=False, product_key="ai_english"):
        user = self.get_user(user_id)
        if not user:
            raise ValueError("用户不存在")
        subscription = self._ensure_legacy_subscription(user, product_key)
        if not self._subscription_can_receive(subscription):
            reply = "这个服务还没有开通或权益已到期，请联系管理员开通 7 天试用或续费。"
            if force:
                self.channel.send_text(user, reply)
                return reply
            return None
        if not force and user["subscription_status"] != "active":
            return None
        content = self._select_content(user, product_key)
        if not content:
            raise ValueError("没有可用知识点")
        message = format_content_push(content)
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
            self.db.execute(
                """UPDATE user_subscriptions
                SET current_content_id = ?, last_push_date = ?
                WHERE user_id = ? AND product_key = ?""",
                (content["id"], date.today().isoformat(), user_id, product_key),
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
        subscriptions = self.db.all(
            """SELECT s.*, u.subscription_status AS user_status
            FROM user_subscriptions s
            JOIN users u ON u.id = s.user_id
            WHERE s.preferred_hour = ?
              AND u.subscription_status = 'active'
              AND s.status IN ('trial', 'paid', 'active')
              AND (s.last_push_date IS NULL OR s.last_push_date != ?)""",
            (hour, today),
        )
        sent = 0
        for subscription in subscriptions:
            if self._subscription_can_receive(subscription) and self.push_one(
                subscription["user_id"], product_key=subscription["product_key"]
            ):
                sent += 1
        return sent

    def dashboard(self):
        return {
            "users": self.db.one("SELECT COUNT(*) AS value FROM users")["value"],
            "active": self.db.one("SELECT COUNT(*) AS value FROM users WHERE subscription_status = 'active'")["value"],
            "products": self.db.one("SELECT COUNT(*) AS value FROM products WHERE enabled = 1")["value"],
            "subscriptions": self.db.one("SELECT COUNT(*) AS value FROM user_subscriptions WHERE status IN ('trial', 'paid', 'active')")["value"],
            "pending_content": self.db.one("SELECT COUNT(*) AS value FROM content_items WHERE review_status = 'pending'")["value"],
            "messages": self.db.one("SELECT COUNT(*) AS value FROM messages")["value"],
            "pushes": self.db.one("SELECT COUNT(*) AS value FROM push_jobs WHERE status = 'sent'")["value"],
            "model_configured": self.agent.configured,
        }
