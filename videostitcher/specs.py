from pathlib import Path
from pendulum import DateTime
from pendulum import from_timestamp

import ffmpeg
import json
import sys


class Specs:
    """Represents a JSON file and accompanying video/audio files.
    Instantiate passing the JSON file path as the only argument to `__init__`.
    """

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        with open(filepath) as fh:
            self.config = json.load(fh)
        self.inputs = {}
        for fileinfo in self.config["inputs"]:
            print(f"Analyzing {fileinfo['filename']}", file=sys.stderr)
            self.inputs[fileinfo["streamname"]] = ffmpeg.probe(
                self.absolute_path(fileinfo["filename"])
            )

    def absolute_path(self, filename: str) -> str:
        """If the passed in file path is not absolute, convert it to absolute,
        using the directory of the JSON specs file (self.filepath) as root.
        """
        return str(self.filepath.parent / filename)


def parse_ts(ts: int) -> DateTime:
    """Returns a Pendulum datetime parsed from the passed datetime from epoch in microseconds."""
    return from_timestamp(ts / 1000 ** 2)
