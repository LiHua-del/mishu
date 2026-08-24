import json
import re
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class StaticUiContractTests(unittest.TestCase):
    def test_asset_versions_stay_synchronized(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        app = (WEB / "js" / "app.js").read_text(encoding="utf-8")
        worker = (WEB / "sw.js").read_text(encoding="utf-8")
        versions = set(re.findall(r"\?v=(\d+)", html + app + worker))
        self.assertEqual(len(versions), 1)
        version = next(iter(versions))
        self.assertIn(f"mishu-static-v{version}", worker)

    def test_theme_picker_exposes_all_five_themes(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        themes = re.findall(r'data-accent-theme="([^"]+)"', html)
        self.assertEqual(themes, ["coral", "amber", "sage", "blue", "plum"])
        self.assertIn('aria-label="选择主题色"', html)
        self.assertIn('aria-expanded="false"', html)

    def test_frontend_modules_are_loaded_before_bootstrap_and_cached(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        worker = (WEB / "sw.js").read_text(encoding="utf-8")
        scripts = ["preference-model.js", "app-config.js", "app-state.js", "app-sync.js", "app.js"]
        positions = [html.index(f"/js/{name}") for name in scripts]
        self.assertEqual(positions, sorted(positions))
        for name in scripts:
            self.assertTrue((WEB / "js" / name).exists())
            self.assertIn(f"/js/{name}", worker)

    def test_service_worker_never_caches_api_responses(self):
        worker = (WEB / "sw.js").read_text(encoding="utf-8")
        api_branch = worker.split("if (url.pathname.startsWith('/api/'))", 1)[1].split("return;", 1)[0]
        self.assertNotIn("caches.open", api_branch)
        self.assertNotIn("caches.match", api_branch)
        self.assertIn("status: 503", api_branch)

    def test_logo_and_install_icons_have_expected_dimensions(self):
        expected = {
            "logo-mark.png": (256, 256),
            "icon-192.png": (192, 192),
            "icon-512.png": (512, 512),
            "apple-touch-icon.png": (180, 180),
        }
        for name, dimensions in expected.items():
            with self.subTest(name=name):
                data = (WEB / "icons" / name).read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(struct.unpack(">II", data[16:24]), dimensions)

    def test_manifest_references_existing_png_icons(self):
        manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
        for icon in manifest["icons"]:
            self.assertEqual(icon["type"], "image/png")
            self.assertTrue((WEB / icon["src"].lstrip("/")).exists())

    def test_stylesheet_braces_and_dialog_action_contract(self):
        css = (WEB / "css" / "app.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", css)
        self.assertIn(".dialog-main-actions a{border:1px solid var(--ink);background:var(--ink);color:#fff", css)


if __name__ == "__main__":
    unittest.main()
