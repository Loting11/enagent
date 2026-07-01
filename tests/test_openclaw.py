import os
import tempfile
import unittest

from src.channel import WeComChannel
from src.db import Database
from src.openclaw import DEFAULT_CLI_PATH, OpenClawClient, OpenClawError


class FakeRunner:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))

        class Result:
            pass

        result = Result()
        result.returncode = self.returncode
        result.stdout = self.stdout
        result.stderr = self.stderr
        return result


class OpenClawClientTest(unittest.TestCase):
    def test_default_cli_path_is_portable(self):
        self.assertEqual(DEFAULT_CLI_PATH, "openclaw")

    def test_send_text_uses_configured_account_and_target(self):
        runner = FakeRunner()
        client = OpenClawClient(
            cli_path="/bin/openclaw",
            channel="openclaw-weixin",
            account_id="wechat-bot",
            enabled=True,
            runner=runner,
        )

        client.send_text("user-123", "hello")

        command = runner.calls[0][0]
        self.assertEqual(command[:3], ["/bin/openclaw", "message", "send"])
        self.assertIn("--account", command)
        self.assertIn("wechat-bot", command)
        self.assertIn("--target", command)
        self.assertIn("user-123", command)
        self.assertIn("--message", command)
        self.assertIn("hello", command)

    def test_send_text_can_override_account(self):
        runner = FakeRunner()
        client = OpenClawClient(
            cli_path="/bin/openclaw",
            channel="openclaw-weixin",
            account_id="default-bot",
            enabled=True,
            runner=runner,
        )

        client.send_text("user-123", "hello", account_id="second-bot")

        command = runner.calls[0][0]
        self.assertIn("--account", command)
        self.assertIn("second-bot", command)
        self.assertNotIn("default-bot", command)

    def test_login_command_can_target_channel_and_account(self):
        client = OpenClawClient(
            cli_path="/bin/sh",
            channel="openclaw-weixin",
            account_id="wechat-bot",
            enabled=True,
            runner=FakeRunner(),
        )

        self.assertEqual(
            client.login_command("new-bot"),
            ["/bin/sh", "channels", "login", "--channel", "openclaw-weixin", "--account", "new-bot"],
        )

    def test_rejects_unconfigured_client(self):
        client = OpenClawClient(enabled=False, account_id="wechat-bot", runner=FakeRunner())
        with self.assertRaisesRegex(OpenClawError, "尚未启用"):
            client.send_text("user-123", "hello")


class OpenClawChannelTest(unittest.TestCase):
    def test_openclaw_user_ids_route_to_openclaw_client(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = Database(os.path.join(temp.name, "test.db"))
        db.initialize([])
        runner = FakeRunner()
        channel = WeComChannel(
            db,
            openclaw_client=OpenClawClient(
                cli_path="/bin/openclaw",
                channel="openclaw-weixin",
                account_id="wechat-bot",
                enabled=True,
                runner=runner,
            ),
        )
        user = {"id": 1, "channel_user_id": "openclaw:user-123"}
        db.execute(
            "INSERT INTO users (id, name, channel_user_id) VALUES (1, '微信用户', 'openclaw:user-123')"
        )

        result = channel.send_text(user, "hello")

        self.assertEqual(result["channel"], "openclaw")
        self.assertIn("user-123", runner.calls[0][0])
        message = db.one("SELECT * FROM messages WHERE user_id = 1")
        self.assertEqual(message["kind"], "text")
        self.assertEqual(message["text"], "hello")

    def test_openclaw_user_ids_can_include_account_id(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = Database(os.path.join(temp.name, "test.db"))
        db.initialize([])
        runner = FakeRunner()
        channel = WeComChannel(
            db,
            openclaw_client=OpenClawClient(
                cli_path="/bin/openclaw",
                channel="openclaw-weixin",
                account_id="default-bot",
                enabled=True,
                runner=runner,
            ),
        )
        user = {"id": 1, "channel_user_id": "openclaw:second-bot:user-123"}
        db.execute(
            "INSERT INTO users (id, name, channel_user_id) VALUES (1, '微信用户', 'openclaw:second-bot:user-123')"
        )

        channel.send_text(user, "hello")

        command = runner.calls[0][0]
        self.assertIn("second-bot", command)
        self.assertIn("user-123", command)
        self.assertNotIn("default-bot", command)


if __name__ == "__main__":
    unittest.main()
