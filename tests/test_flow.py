import os
import tempfile
import unittest

from src.agent import AgentService
from src.channel import MockWeComChannel
from src.content import DEMO_CONTENT, INDUSTRY_BRIEFINGS
from src.db import Database
from src.service import EnglishAgentService, format_learning_push


class AgentFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp.name, "test.db"))
        self.db.initialize(DEMO_CONTENT + INDUSTRY_BRIEFINGS)
        self.service = EnglishAgentService(self.db, MockWeComChannel(self.db), AgentService())

    def tearDown(self):
        self.temp.cleanup()

    def test_subscription_push_and_answer(self):
        user = self.service.create_user("小明", "wx_test")
        self.assertEqual(user["subscription_status"], "pending")
        self.service.receive(user["id"], "开始")
        self.assertEqual(self.service.get_user(user["id"])["subscription_status"], "active")
        self.service.push_one(user["id"])
        current = self.service.get_user(user["id"])["current_content_id"]
        item = self.db.one("SELECT * FROM content_items WHERE id = ?", (current,))
        reply = self.service.receive(user["id"], item["answer"])
        self.assertIn("回答正确", reply)

    def test_learning_push_message_is_readable_in_wechat(self):
        item = self.db.one("SELECT * FROM content_items ORDER BY id ASC LIMIT 1")
        message = format_learning_push(item)

        self.assertIn("今日 AI 英语\n", message)
        self.assertIn("\n\n含义\n", message)
        self.assertIn("\n\n说明\n", message)
        self.assertIn("\n\n例句\n", message)
        self.assertIn("\n\n小测试\n", message)
        self.assertIn("\n\nA. ", message)
        self.assertIn("\n\nB. ", message)
        self.assertIn("\n\nC. ", message)
        self.assertTrue(message.endswith("回复 A / B / C 即可"))

    def test_pause_blocks_scheduled_push(self):
        user = self.service.create_user("小红", "wx_test_2")
        self.service.receive(user["id"], "暂停")
        self.assertIsNone(self.service.push_one(user["id"]))

    def test_auto_subscribe_contact_is_idempotent(self):
        user, created = self.service.auto_subscribe_contact("小新", "788123")
        self.assertTrue(created)
        self.assertEqual(user["subscription_status"], "active")
        same_user, created_again = self.service.auto_subscribe_contact("小新", "788123")
        self.assertFalse(created_again)
        self.assertEqual(same_user["id"], user["id"])
        self.assertEqual(len(self.service.messages(user["id"])), 1)

    def test_openclaw_user_requires_admin_approval(self):
        reply = self.service.receive_from_channel("openclaw:user-1", "开始", name="微信用户")
        user = self.service.get_user_by_channel_id("openclaw:user-1")
        self.assertEqual(user["subscription_status"], "pending")
        self.assertIn("管理员审核", reply)

        approved = self.service.approve_user(user["id"])
        self.assertEqual(approved["subscription_status"], "active")
        self.service.receive(approved["id"], "来一个")
        self.assertIsNotNone(self.service.get_user(approved["id"])["current_content_id"])

    def test_user_can_subscribe_to_multiple_products(self):
        user = self.service.create_user("小林", "wx_multi")
        self.service.approve_user(user["id"])
        english = self.service.open_trial_subscription(user["id"], "ai_english")
        briefing = self.service.open_trial_subscription(user["id"], "ai_briefing")

        self.assertEqual(english["status"], "trial")
        self.assertEqual(briefing["status"], "trial")
        self.assertEqual(len(self.service.subscriptions(user["id"])), 2)

        english_message = self.service.receive(user["id"], "来一个英语")
        briefing_message = self.service.receive(user["id"], "今日早报")

        self.assertIn("今日 AI 英语", english_message)
        self.assertIn("AI 行业早报", briefing_message)

    def test_unopened_product_does_not_push(self):
        user = self.service.create_user("小周", "wx_unopened")
        self.service.approve_user(user["id"])

        reply = self.service.receive(user["id"], "今日早报")

        self.assertIn("还没有开通", reply)


if __name__ == "__main__":
    unittest.main()
