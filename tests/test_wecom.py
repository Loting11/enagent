import base64
import unittest

from src.wecom import WeComCrypto, WeComError, parse_encrypted_xml, parse_message_xml


class WeComCryptoTest(unittest.TestCase):
    def setUp(self):
        self.aes_key = base64.b64encode(bytes(range(32))).decode("ascii")[:-1]
        self.crypto = WeComCrypto("callback-token", self.aes_key, "ww-corp-id")

    def test_encrypt_decrypt_and_signature(self):
        xml = "<xml><FromUserName>zhangsan</FromUserName><MsgType>text</MsgType></xml>"
        result = self.crypto.encrypt(xml, timestamp="1710000000", nonce="12345")
        self.crypto.verify(
            result["signature"], result["timestamp"], result["nonce"], result["encrypt"]
        )
        self.assertEqual(self.crypto.decrypt(result["encrypt"]), xml)

    def test_rejects_bad_signature(self):
        result = self.crypto.encrypt("hello", timestamp="1710000000", nonce="12345")
        with self.assertRaises(WeComError):
            self.crypto.verify("bad", "1710000000", "12345", result["encrypt"])

    def test_parses_callback_xml(self):
        outer = b"<xml><Encrypt><![CDATA[ciphertext]]></Encrypt></xml>"
        self.assertEqual(parse_encrypted_xml(outer), "ciphertext")
        inner = "<xml><FromUserName><![CDATA[zhangsan]]></FromUserName><Content>A</Content></xml>"
        message = parse_message_xml(inner)
        self.assertEqual(message["FromUserName"], "zhangsan")
        self.assertEqual(message["Content"], "A")


if __name__ == "__main__":
    unittest.main()
