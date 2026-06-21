import os
import tempfile
import unittest

from src.agent import AgentService
from src.channel import MockWeComChannel
from src.content import DEMO_CONTENT
from src.db import Database
from src.service import EnglishAgentService


class AgentFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp.name, "test.db"))
        self.db.initialize(DEMO_CONTENT)
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


if __name__ == "__main__":
    unittest.main()
