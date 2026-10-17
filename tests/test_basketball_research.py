"""Public news collection cannot establish eligibility or access ESPN credentials."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

from basketball.cli import parser, run
from basketball.config import read_json
from basketball.research import Firecrawl, collect, public_nba_url


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"_data": self.tmp.name}
        self.url = "https://www.nba.com/news/example-retirement"
        self.client = Mock()
        self.client.search.side_effect = [[], [{"url": self.url, "title": "Player retired"}]]
        self.client.scrape.return_value = {"markdown": "Player retired years ago.", "metadata": {"statusCode": 200}}

    def test_old_retirement_search_is_unrestricted_and_evidence_is_not_eligibility(self):
        result = collect(self.cfg, "Player Name", client=self.client)
        self.assertTrue(self.client.search.call_args_list[0].args[2].startswith("cdr:"))
        self.assertIsNone(self.client.search.call_args_list[1].args[2])
        saved = read_json(result["evidence"])
        self.assertEqual(saved["articles"][0]["markdown"], "Player retired years ago.")
        self.assertEqual(saved["eligibility"], "unknown")
        self.assertEqual(saved["review_status"], "unreviewed")
        self.assertIn(self.url, Path(result["report"]).read_text())

    def test_no_results_or_partial_failure_never_means_active(self):
        for results in ([[], []], [[], [{"url": self.url}]]):
            client = Mock()
            client.search.side_effect = results
            client.scrape.side_effect = ValueError("unavailable")
            result = collect(self.cfg, "Player Name", client=client)
            self.assertFalse(result["complete"])
            self.assertEqual(result["eligibility"], "unknown")

    def test_private_urls_and_spoofed_domains_are_rejected_before_requests(self):
        for url in ("https://fantasy.espn.com/basketball/team?leagueId=1", "https://nba.com.evil.com/news/a",
                    "https://www.nba.com/news/a?token=secret", "http://www.nba.com/news/a",
                    "https://secret@www.nba.com/news/a", "https://www.nba.com/account"):
            with self.assertRaises(ValueError):
                collect(self.cfg, "Player", url=url, client=self.client)
        self.client.search.assert_not_called()
        self.client.scrape.assert_not_called()
        self.assertEqual(public_nba_url(self.url), self.url)

    def test_deduplicates_articles_and_preserves_separate_captures(self):
        self.client.search.side_effect = None
        self.client.search.return_value = [{"url": self.url}]
        first = collect(self.cfg, "Player", client=self.client)
        self.assertEqual(self.client.scrape.call_count, 1)
        second = collect(self.cfg, "Player", client=self.client)
        self.assertNotEqual(first["evidence"], second["evidence"])
        self.assertTrue(Path(first["evidence"]).exists())

    def test_http_uses_only_firecrawl_key_and_requests_uncached_content(self):
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(json.dumps({"success": True, "data": {
            "markdown": "article", "metadata": {"statusCode": 200, "sourceURL": self.url}}}).encode()))
        response.__exit__ = Mock(return_value=False)
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test", "ESPN_S2": "private", "ESPN_SWID": "private"}), \
                patch("basketball.research.urllib.request.urlopen", return_value=response) as request:
            Firecrawl().scrape(self.url)
        sent = request.call_args.args[0]
        self.assertEqual(sent.get_header("Authorization"), "Bearer fc-test")
        self.assertIsNone(sent.get_header("Cookie"))
        self.assertNotIn("private", sent.data.decode())
        self.assertEqual(json.loads(sent.data)["maxAge"], 0)

    def test_provider_errors_and_redirects_do_not_become_evidence(self):
        error = urllib.error.HTTPError("https://api.firecrawl.dev", 429, "limit", {}, io.BytesIO(b"fc-secret"))
        with patch("basketball.research.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(ValueError, "HTTP 429") as caught:
                Firecrawl().search("Player", 3)
        self.assertNotIn("fc-secret", str(caught.exception))
        bad = {"markdown": "article", "metadata": {"url": "https://fantasy.espn.com/basketball/team"}}
        with patch.object(Firecrawl, "post", return_value=bad):
            with self.assertRaises(ValueError):
                Firecrawl().scrape(self.url)

    def test_cli_research_does_not_load_league_snapshot(self):
        args = parser().parse_args(["research", "Player", "--url", self.url])
        with patch("basketball.cli.load", return_value=self.cfg), \
                patch("basketball.cli.load_snapshot", side_effect=AssertionError("ESPN accessed")), \
                patch("basketball.research.collect", return_value={"eligibility": "unknown"}) as collector:
            self.assertEqual(run(args), {"eligibility": "unknown"})
        collector.assert_called_once_with(self.cfg, "Player", 3, 30, self.url)


if __name__ == "__main__":
    unittest.main()
