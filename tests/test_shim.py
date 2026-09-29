"""
Tests for ndev.win.core.shim (Windows shimgen integration).
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from ndev.win.core import shim


class TestShim(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="ndev_shim_test_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_shim_exe_exists(self):
        self.assertTrue(shim.SHIM_EXE.exists(), f"shim.exe not found at {shim.SHIM_EXE}")

    def test_create_and_read_exe_shim(self):
        # Target dummy executable
        target_path = Path(r"C:\Windows\System32\cmd.exe")
        shim_file = shim.create(
            "dummy_cmd",
            target_path,
            args="/c echo hello",
            cwd=r"C:\Windows",
            path_prepend=r"C:\Windows\System32",
            shim_dir=self.test_dir,
        )

        self.assertEqual(shim_file, self.test_dir / "dummy_cmd.exe")
        self.assertTrue((self.test_dir / "dummy_cmd.exe").exists())
        self.assertTrue((self.test_dir / "dummy_cmd.shim").exists())

        cfg = shim.read_shim("dummy_cmd", shim_dir=self.test_dir)
        self.assertEqual(cfg.get("path"), str(target_path))
        self.assertEqual(cfg.get("args"), "/c echo hello")
        self.assertEqual(cfg.get("cwd"), r"C:\Windows")
        self.assertEqual(cfg.get("path_prepend"), r"C:\Windows\System32")

    def test_list_and_remove_shim(self):
        target_path = Path(r"C:\Windows\System32\cmd.exe")
        shim.create("tool_a", target_path, shim_dir=self.test_dir)
        shim.create("tool_b", target_path, shim_dir=self.test_dir)

        shims = shim.list_shims(shim_dir=self.test_dir)
        self.assertIn("tool_a", shims)
        self.assertIn("tool_b", shims)

        removed = shim.remove("tool_a", shim_dir=self.test_dir)
        self.assertTrue(removed)
        self.assertFalse((self.test_dir / "tool_a.exe").exists())
        self.assertFalse((self.test_dir / "tool_a.shim").exists())

        shims_after = shim.list_shims(shim_dir=self.test_dir)
        self.assertNotIn("tool_a", shims_after)
        self.assertIn("tool_b", shims_after)

    def test_clean_legacy_option(self):
        target_path = Path(r"C:\Windows\System32\cmd.exe")
        # Create mock legacy .bat, .cmd, and .ps1
        (self.test_dir / "preserve_test.bat").write_text("@echo off", encoding="utf-8")
        (self.test_dir / "preserve_test.cmd").write_text("@echo off", encoding="utf-8")
        (self.test_dir / "preserve_test.ps1").write_text("& echo hi", encoding="utf-8")

        # When clean_legacy is False, legacy files remain
        shim.create("preserve_test", target_path, shim_dir=self.test_dir, clean_legacy=False)
        self.assertTrue((self.test_dir / "preserve_test.exe").exists())
        self.assertTrue((self.test_dir / "preserve_test.bat").exists())
        self.assertTrue((self.test_dir / "preserve_test.cmd").exists())
        self.assertTrue((self.test_dir / "preserve_test.ps1").exists())

        # When clean_legacy is True, legacy files are unlinked
        shim.create("preserve_test", target_path, shim_dir=self.test_dir, clean_legacy=True)
        self.assertTrue((self.test_dir / "preserve_test.exe").exists())
        self.assertFalse((self.test_dir / "preserve_test.bat").exists())
        self.assertFalse((self.test_dir / "preserve_test.cmd").exists())
        self.assertFalse((self.test_dir / "preserve_test.ps1").exists())


if __name__ == "__main__":
    unittest.main()
