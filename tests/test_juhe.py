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

    @patch("src.juhe.urlopen")
    def test_uploads_and_sends_voice(self, mock_open):
        mock_open.side_effect = [
            FakeResponse(
                {
                    "error_code": 0,
                    "data": {
                        "cdn_dns": "cdn.example",
                        "client_version": "5.0.0",
                        "corp_id": "corp",
                        "vid": "vid",
                    },
                }
            ),
            FakeResponse(
                {
                    "error_code": 0,
                    "data": {
                        "file_id": "file-id",
                        "file_size": 1024,
                        "file_md5": "md5",
                        "aes_key": "aes",
                    },
                }
            ),
            FakeResponse({"error_code": 0, "data": {}}),
        ]

        self.client.send_voice_url("788123", "https://agent.example/voice.silk", 3)

        requests = [json.loads(call.args[0].data.decode("utf-8")) for call in mock_open.call_args_list]
        self.assertEqual([item["path"] for item in requests], [
            "/cdn/get_cdn_info", "/cloud/c2c_upload", "/msg/send_voice"
        ])
        self.assertEqual(requests[1]["data"]["file_type"], 5)
        self.assertEqual(requests[2]["data"]["conversation_id"], "S:788123")
        self.assertEqual(requests[2]["data"]["voice_time"], 3)

    @patch("src.juhe.urlopen")
    def test_private_cdn_upload_is_not_wrapped(self, mock_open):
        client = JuheClient(
            api_url="https://supplier.test/open/GuidRequest",
            app_key="key",
            app_secret="secret",
            guid="device-guid",
            private_cdn_url="http://127.0.0.1:34789",
        )
        mock_open.side_effect = [
            FakeResponse(
                {"error_code": 0, "data": {"cdn_dns": "cdn", "client_version": "5", "corp_id": "c", "vid": "v"}}
            ),
            FakeResponse(
                {"error_code": 0, "data": {"file_id": "id", "file_size": 1, "file_md5": "md5", "aes_key": "aes"}}
            ),
        ]
        client.upload_c2c("https://agent.example/voice.m4a")
        private_request = mock_open.call_args_list[1].args[0]
        self.assertEqual(private_request.full_url, "http://127.0.0.1:34789/cloud/c2c_upload")
        payload = json.loads(private_request.data.decode("utf-8"))
        self.assertNotIn("app_secret", payload)
        self.assertEqual(payload["file_type"], 5)


if __name__ == "__main__":
    unittest.main()
