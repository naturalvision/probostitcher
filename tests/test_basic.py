from pathlib import Path
from videostitcher import Specs

import os
import tempfile


CREATE_VIDEO = False
CREATE_VIDEO = True


def test_first():
    specs = Specs(Path(__file__).parent / "test-files" / "example.json")
    fh, tmp_path = tempfile.mkstemp(".webm")
    os.fdopen(fh).close()
    os.unlink(tmp_path)
    final = specs.get_final(tmp_path)
    print(" \\\n".join(final.compile()))  # Smoke test
    # Uncomment the next line to see the rendering plan graph
    # final.view()
    if CREATE_VIDEO:
        final.run()
        print(f"Written file {tmp_path}")
