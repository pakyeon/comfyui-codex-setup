"""Run with python -m unittest -v; no GPU or ComfyUI needed."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tomlkit
import setup


class SetupTests(unittest.TestCase):
    def test_local_url_rejects_remote_and_credentials(self):
        for value in ("http://example.com:8188", "http://127.0.0.1:8188/api",
                      "https://localhost:8188", "http://user:secret@localhost:8188",
                      "http://localhost:8188/?token=x", "http://localhost"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                setup.local_url(value)
        for value in ("http://localhost:8188", "http://127.0.0.1:8188/", "http://[::1]:8188"):
            self.assertEqual(setup.local_url(value), value.rstrip("/"))

    def test_config_preserves_other_servers_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            original = '# personal comment\nmodel = "existing"\n[mcp_servers.other]\ncommand = "other-tool"\n'
            path.write_text(original, encoding="utf-8")
            entry = {"command": "C:\\path with spaces\\comfy-mcp.exe", "args": [],
                     "env": {"COMFY_CODEX_SETUP": "1", "COMFY_WHERE": "local"}}
            self.assertTrue(setup.update_config(path, entry))
            contents = path.read_text(encoding="utf-8")
            document = tomlkit.parse(contents)
            self.assertIn("# personal comment", contents)
            self.assertEqual(document["mcp_servers"]["other"]["command"], "other-tool")
            self.assertEqual(document["model"], "existing")
            self.assertFalse(setup.update_config(path, entry))
            backups = list(Path(folder).glob("*.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), original)

    def test_conflicting_server_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            original = '[mcp_servers.comfyui]\ncommand = "my-server"\n'
            path.write_text(original, encoding="utf-8")
            with self.assertRaises(RuntimeError):
                setup.update_config(path, {"command": "new"})
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertTrue(setup.update_config(path, {"command": "new"}, replace=True))

    def test_desktop_shared_paths_are_recorded_without_editing_yaml(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkout = root / "ComfyUI"
            checkout.mkdir()
            shared = root / "Shared Models"
            shared.mkdir()
            config = root / "desktop.yaml"
            source = f"desktop:\n  base_path: '{shared.as_posix()}'\n  is_default: true\n  loras: loras/\n"
            config.write_text(source, encoding="utf-8")
            self.assertEqual(setup.model_roots(checkout, ["main.py", "--extra-model-paths-config", str(config)]), [str(shared.resolve())])
            self.assertEqual(config.read_text(encoding="utf-8"), source)

    def test_windows_and_macos_install_locations(self):
        with patch("setup.platform.system", return_value="Windows"), patch.dict("setup.os.environ", {"LOCALAPPDATA": "C:/Local"}):
            self.assertEqual(setup.default_install_dir(), Path("C:/Local/comfyui-codex"))
        with patch("setup.platform.system", return_value="Darwin"), patch("setup.Path.home", return_value=Path("/Users/sample")):
            self.assertEqual(setup.default_install_dir(), Path("/Users/sample/Library/Application Support/comfyui-codex"))

    def test_official_skills_install_is_idempotent_and_preserves_conflicts(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "skills"
            setup.install_official_skills(dest)
            setup.install_official_skills(dest)
            for name in setup.OFFICIAL_SKILLS:
                self.assertTrue((dest / name / "SKILL.md").is_file())
                self.assertEqual(json.loads((dest / name / setup.MARKER).read_text())["version"], "1.22.0")
            target = dest / "comfy-debug" / "SKILL.md"
            target.write_text("user changes", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                setup.install_official_skills(dest)
            self.assertEqual(target.read_text(encoding="utf-8"), "user changes")


if __name__ == "__main__":
    unittest.main()
