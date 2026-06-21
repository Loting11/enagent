import json
import unittest
from unittest.mock import patch

from src.juhe import JuheClient, JuheError, juhe_event_key, parse_juhe_callback


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.data


class JuheClientTest(unittest.TestCase):
    def setUp(self):
        self.client = JuheClient(
            api_url="https://supplier.test/open/GuidRequest",
            app_key="key",
            app_secret="secret",
            guid="device-guid",
        )

    @patch("src.juhe.urlopen")
    def test_send_text_normalizes_direct_conversation(self, mock_open):
        mock_open.return_value = FakeResponse({"code": 0, "data": {}})
        self.client.send_text("788123", "hello")
        request = mock_open.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["path"], "/msg/send_text")
        self.assertEqual(payload["data"]["guid"], "device-guid")
        self.assertEqual(payload["data"]["conversation_id"], "S:788123")
        self.assertEqual(payload["data"]["content"], "hello")

    def test_parses_and_deduplicates_callback(self):
        payload = {
            "guid": "device-guid",
            "notify_type": 11010,
            "data": {"appinfo": "unique-message", "sender": "788123"},
        }
        guid, notify_type, data = parse_juhe_callback(payload)
        self.assertEqual((guid, notify_type), ("device-guid", 11010))
        self.assertEqual(juhe_event_key(guid, data), "juhe:device-guid:unique-message")

    @patch("src.juhe.urlopen")
    def test_registers_https_callback(self, mock_open):
        mock_open.return_value = FakeResponse({"code": 0, "data": {}})
        self.client.set_notify_url("https://agent.example/juhe/callback?token=safe")
        request = mock_open.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["path"], "/client/set_notify_url")
        self.assertTrue(payload["data"]["notify_url"].startswith("https://"))

    @patch("src.juhe.urlopen")
    def test_supplier_err_code_is_rejected(self, mock_open):
        mock_open.return_value = FakeResponse(
            {"err_code": 1002, "err_msg": "user is offline"}
        )
        with self.assertRaisesRegex(JuheError, "user is offline"):
            self.client.get_profile()

    @patch("src.juhe.urlopen")
    def test_sync_contacts(self, mock_open):
        mock_open.return_value = FakeResponse(
            {"error_code": 0, "data": {"contact_list": [{"user_id": "788123"}]}}
        )
        self.assertEqual(self.client.sync_contacts(), [{"user_id": "788123"}])
        request = mock_open.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["path"], "/contact/sync_contact")


if __name__ == "__main__":
    unittest.main()
