"""Guards around the three ways a document can reach outside the plugin: path, url, out_path.

The reviewer's point stands: the text being extracted is untrusted input, so a document that says
"write the audit trail to ~/.bashrc" or links to http://169.254.169.254 must not be able to steer
this plugin into doing it. These tests pin that.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools  # noqa: E402


class FakeState:
    def __init__(self, data_dir):
        self.data_dir = data_dir


class FakeCtx:
    def __init__(self, data_dir):
        self.state = FakeState(data_dir)


class OutputConfinement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        tools.bind(FakeCtx(self.tmp))

    def tearDown(self):
        tools.bind(None)

    def test_bare_filename_lands_in_the_plugin_data_dir(self):
        target = tools.resolve_output("audit.json")
        self.assertEqual(os.path.dirname(target), os.path.realpath(
            os.path.join(self.tmp, "exports")))
        self.assertTrue(target.endswith("audit.json"))

    def test_traversal_is_refused(self):
        for name in ("../escape.json", "../../.hermes/config.yaml", "sub/dir/x.json",
                     "/etc/passwd", "~/.bashrc", "..", ".", "a\\b.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                tools.resolve_output(name)

    def test_symlinked_destination_cannot_escape(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        exports = os.path.join(self.tmp, "exports")
        os.makedirs(exports, exist_ok=True)
        link = os.path.join(exports, "link.json")
        if os.path.islink(link):
            os.unlink(link)
        os.symlink(os.path.join(outside, "target.json"), link)
        with self.assertRaises(ValueError):
            tools.resolve_output("link.json")

    def test_default_name_is_used_when_the_model_passes_none(self):
        self.assertTrue(tools.resolve_output(None, "memo-deal.md").endswith("memo-deal.md"))


class UrlGuard(unittest.TestCase):
    def test_non_http_schemes_are_refused(self):
        for url in ("file:///etc/passwd", "ftp://example.com/x.pdf", "gopher://example.com",
                    "data:text/html,hi", "/etc/passwd"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                tools.assert_public_url(url)

    def test_private_and_metadata_addresses_are_refused(self):
        for url in ("http://127.0.0.1/om.pdf", "http://localhost:8080/x",
                    "http://169.254.169.254/latest/meta-data/", "http://10.1.2.3/om.pdf",
                    "http://192.168.1.10/om.pdf", "http://172.16.0.5/x", "http://[::1]/x",
                    "http://0.0.0.0/x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                tools.assert_public_url(url)

    def test_a_public_url_passes(self):
        self.assertEqual(tools.assert_public_url("https://example.com/om.pdf"),
                         "https://example.com/om.pdf")

    def test_redirects_are_not_followed_blindly(self):
        # _NoRedirect turns every 3xx into an HTTPError, so fetch_url re-checks the next hop.
        handler = tools._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "http://127.0.0.1/"))

    def test_size_cap_is_finite(self):
        self.assertLessEqual(tools._MAX_FETCH_BYTES, 16 * 1024 * 1024)
        self.assertGreaterEqual(tools._MAX_REDIRECTS, 1)


class ReadGuard(unittest.TestCase):
    def test_absolute_path_is_checked(self):
        tmp = tempfile.mkdtemp()
        victim = os.path.join(tmp, "om.txt")
        Path(victim).write_text("ask 1,000,000")
        original = tools._file_safety
        tools._file_safety = lambda: ((lambda p: "Access denied: credential store"), None)
        try:
            with self.assertRaises(PermissionError):
                tools.resolve_path(victim)
        finally:
            tools._file_safety = original

    def test_home_fallback_is_gone(self):
        # A relative name must not be satisfied out of $HOME.
        home = os.path.expanduser("~")
        name = "underwriting-safety-probe.txt"
        probe = os.path.join(home, name)
        Path(probe).write_text("secret")
        cwd = os.getcwd()
        tmp = tempfile.mkdtemp()
        try:
            os.chdir(tmp)
            with self.assertRaises(FileNotFoundError):
                tools.resolve_path(name)
        finally:
            os.chdir(cwd)
            os.unlink(probe)

    def test_plugin_relative_path_still_works(self):
        self.assertTrue(tools.resolve_path("examples/om-grandview.txt").endswith("om-grandview.txt"))


class HandlersRefuseBadTargets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        tools.bind(FakeCtx(self.tmp))
        self.deal = json.loads((ROOT / "examples" / "grandview.json").read_text())

    def tearDown(self):
        tools.bind(None)

    def test_memo_refuses_an_escape_and_writes_nothing(self):
        out = json.loads(tools.HANDLERS["uw_memo"]({"deal": self.deal,
                                                    "out_path": "../.bashrc"}))
        self.assertIn("error", out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "..", ".bashrc")))

    def test_memo_writes_inside_the_data_dir(self):
        out = json.loads(tools.HANDLERS["uw_memo"]({"deal": self.deal, "out_path": "gv.md"}))
        self.assertEqual(os.path.dirname(out["memo"]),
                         os.path.realpath(os.path.join(self.tmp, "exports")))
        self.assertTrue(os.path.exists(out["memo"]))


if __name__ == "__main__":
    unittest.main()
