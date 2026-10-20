import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "skills/supercollider/scripts")
)
from scs_tool.files import publish_no_replace


class FileTests(unittest.TestCase):
    def test_atomic_publication_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage, output = Path(tmp, "private.wav"), Path(tmp, "out.wav")
            stage.write_bytes(b"verified")
            publish_no_replace(stage, output)
            self.assertTrue(output.is_file(), "publication must create output")
            self.assertEqual(output.read_bytes(), b"verified")
            self.assertEqual(output.stat().st_ino, stage.stat().st_ino)
            stage2 = Path(tmp, "other.wav")
            stage2.write_bytes(b"other")
            with self.assertRaises(FileExistsError):
                publish_no_replace(stage2, output)
            self.assertEqual(output.read_bytes(), b"verified")
            dangling = Path(tmp, "dangling")
            dangling.symlink_to("absent")
            with self.assertRaises(FileExistsError):
                publish_no_replace(stage2, dangling)
            self.assertEqual(os.readlink(dangling), "absent")
