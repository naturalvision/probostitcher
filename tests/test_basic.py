from pathlib import Path
from videostitcher import Specs

import os
import tempfile


def test_first():
    specs = Specs(Path(__file__).parent / "test-files" / "example.json")
    fh, tmp_path = tempfile.mkstemp(".mp4")
    os.fdopen(fh).close()
    os.unlink(tmp_path)
    final = specs.get_final(tmp_path)
    final.run()
    print(f"Written file {tmp_path}")
