import argparse
import unittest
from email.message import Message
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from scrape_ransomware_live import URL, fetch_html, main, positive_timeout


class ScraperTests(unittest.TestCase):
    def response(self, content_type: str, body: bytes) -> MagicMock:
        response = MagicMock()
        response.headers = Message()
        response.headers["Content-Type"] = content_type
        response.read.return_value = body
        response.__enter__.return_value = response
        return response

    @patch("scrape_ransomware_live.urlopen")
    def test_preserves_html_bytes_and_passes_timeout(self, urlopen: MagicMock) -> None:
        html = b"<!doctype html><html><body>\xc3\xa9</body></html>"
        urlopen.return_value = self.response("text/html; charset=utf-8", html)
        self.assertEqual(fetch_html(12), html)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, URL)
        self.assertIn("User-agent", request.headers)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 12)

    @patch("scrape_ransomware_live.urlopen")
    def test_rejects_non_html_and_empty_responses(self, urlopen: MagicMock) -> None:
        for content_type, body in [
            ("application/json", b"{}"),
            ("text/html", b" \n"),
        ]:
            with self.subTest(content_type=content_type, body=body):
                urlopen.return_value = self.response(content_type, body)
                with self.assertRaises(ValueError):
                    fetch_html(30)

    def test_timeout_validation(self) -> None:
        self.assertEqual(positive_timeout("2.5"), 2.5)
        for value in ["0", "-1", "nan", "inf", "invalid"]:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    positive_timeout(value)

    @patch("scrape_ransomware_live.sys.argv", ["scrape_ransomware_live.py"])
    @patch("scrape_ransomware_live.sys.stderr")
    @patch("scrape_ransomware_live.Path.write_bytes")
    @patch("scrape_ransomware_live.urlopen")
    def test_http_failure_does_not_write_output(
        self, urlopen: MagicMock, write_bytes: MagicMock, stderr: MagicMock,
    ) -> None:
        urlopen.side_effect = HTTPError(URL, 503, "Unavailable", Message(), None)
        self.assertEqual(main(), 1)
        write_bytes.assert_not_called()
        self.assertTrue(stderr.write.called)


if __name__ == "__main__":
    unittest.main()
