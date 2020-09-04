#!/usr/bin/env python
import json
import sys

import ffmpeg


class Specs:
    def __init__(self, filepath):
        with open(filepath) as fh:
            self.config = json.load(fh)
        self.inputs = {}
        for fileinfo in self.config["inputs"]:
            print(f"Analyzing {fileinfo['filename']}", file=sys.stderr)
            self.inputs[fileinfo["streamname"]] = ffmpeg.probe(fileinfo["filename"])


if __name__ == "__main__":
    specs = Specs("example.json")
    output_start = specs.config["output_start"]
    output_duration = specs.config["output_duration"]
    inputs = []
    for input_info in specs.config["inputs"]:
        # stream_delay is the length of time between the start of this stream and te start of the output
        # A positive value means this input should be trimmed, and starts as the output starts.
        # A negative value means this input should be delayed, and starts at a later point than the main output.
        stream_delay = output_start - input_info["start"]
        # Only append this to the inputs if it contributes to the final video.
        inputs.append(ffmpeg.input(input_info["filename"]))

    out, _ = inputs[0].output("out.mp4", t=output_duration).overwrite_output().run()
