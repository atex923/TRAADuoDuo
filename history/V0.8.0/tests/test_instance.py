import sys
import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from traaduoduo.instance import MacInstance


@unittest.skipUnless(sys.platform == 'darwin','macOS process lock')
class InstanceTests(unittest.TestCase):
    def test_duplicate_exits_and_kernel_lock_releases(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            first = MacInstance(path)
            try:
                second = MacInstance(path)
                self.assertTrue(first.owner)
                self.assertFalse(second.owner)
                second.close()
            finally:
                first.close()
            third = MacInstance(path)
            self.assertTrue(third.owner)
            third.close()
