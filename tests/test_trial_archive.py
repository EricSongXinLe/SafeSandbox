import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_session_matrix as controller


class TrialArchiveTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.staged = self.root / "staging" / "trial"
        self.staged.mkdir(parents=True)
        self.archive = self.root / "archive"
        self.archive.mkdir()
        self.outside = self.root / "outside"
        self.outside.write_bytes(b"unchanged")
        self.hashes = {}

    def copy(self):
        controller.copy_trial_artifacts(
            self.staged, self.archive, os.getuid(), self.hashes
        )

    def assert_rejected(self):
        with self.assertRaises((OSError, RuntimeError)):
            self.copy()
        self.assertEqual(self.outside.read_bytes(), b"unchanged")
        self.assertEqual(list(self.archive.iterdir()), [])

    def test_copies_only_bytes_and_hashes(self):
        manifest = self.staged / "manifest.json"
        manifest.write_bytes(b"{}")
        self.copy()
        self.assertEqual((self.archive / manifest.name).read_bytes(), b"{}")
        self.assertEqual(self.hashes, {manifest.name: hashlib.sha256(b"{}").hexdigest()})
        self.assertTrue(manifest.exists())

    def test_rejects_symlink_file(self):
        (self.staged / "manifest.json").symlink_to(self.outside)
        self.assert_rejected()

    def test_rejects_symlink_ancestor(self):
        (self.staged / "manifest.json").write_bytes(b"{}")
        alias = self.root / "alias"
        alias.symlink_to(self.staged.parent, target_is_directory=True)
        self.staged = alias / self.staged.name
        self.assert_rejected()

    def test_rejects_hardlink(self):
        os.link(self.outside, self.staged / "manifest.json")
        self.assert_rejected()

    def test_rejects_fifo(self):
        os.mkfifo(self.staged / "manifest.json")
        self.assert_rejected()

    def test_rejects_controller_owned_filename(self):
        (self.staged / "controller_status.json").symlink_to(self.outside)
        self.assert_rejected()

    def test_rejects_oversized_file(self):
        (self.staged / "manifest.json").write_bytes(b"{}")
        with patch.object(controller, "MAX_ARTIFACT_BYTES", 1):
            self.assert_rejected()

    def test_rejects_replacement_between_stat_and_open(self):
        manifest = self.staged / "manifest.json"
        manifest.write_bytes(b"{}")
        replacement = self.staged / "replacement"
        real_open = os.open

        def replace_on_open(path, *args, **kwargs):
            if path == manifest.name:
                replacement.write_bytes(b"[]")
                replacement.replace(manifest)
            return real_open(path, *args, **kwargs)

        with patch.object(controller.os, "open", side_effect=replace_on_open):
            self.assert_rejected()
