from ffmpeg.nodes import OutputStream
from pathlib import Path
from pendulum import DateTime
from pendulum import from_timestamp
from pendulum import Period

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
            fileinfo["filename"] = self.absolute_path(fileinfo["filename"])
            print(f"Analyzing {fileinfo['filename']}", file=sys.stderr)
            self.inputs[fileinfo["streamname"]] = ffmpeg.probe(fileinfo["filename"])

    def absolute_path(self, filename: str) -> str:
        """If the passed in file path is not absolute, convert it to absolute,
        using the directory of the JSON specs file (self.filepath) as root.
        """
        return str(self.filepath.parent / filename)

    def render(self, destination: str):
        """Render the video as specced, saving it in the path given as `destination`."""
        self.get_final(destination).run()

    def get_final(self, destination: str) -> OutputStream:
        """Returns an OutputStream object representing the work needed to produce the
        final output. Useful methods on that object are `view()` (shows a graphical
        representation of the video processing graph) and `run()` (actually produces the file)"""
        output_start = parse_ts(int(self.config["output_start"]))
        output_duration = self.config["output_duration"]
        output_end = output_start.add(seconds=output_duration)
        output_period = output_end - output_start
        inputs = {}
        audio_streams = []
        for input_info in self.config["inputs"]:
            input_start = parse_ts(int(input_info["start"]))
            input_file_info = self.inputs[input_info["streamname"]]
            input_duration = float(input_file_info["format"]["duration"])
            input_end = input_start.add(seconds=input_duration)
            input_period = input_end - input_start

            # Only append this to the inputs if it contributes to the final video.
            if overlaps(output_period, input_period):
                # stream_delay is the length of time between the start of this stream and te start of the output
                # A positive value means this input should be trimmed, and starts as the output starts.
                # A negative value means this input should be delayed, and starts at a later point than the main output.
                stream_delay = (
                    output_start - parse_ts(input_info["start"])
                ).in_seconds()
                input = ffmpeg.input(input_info["filename"])
                if stream_delay > 0:
                    input = input.filter("trim", start=stream_delay).filter(
                        "setpts", "PTS-STARTPTS"
                    )
                    print(
                        f"Stream {input_info['streamname']} starts before main start: trimming",
                        file=sys.stderr,
                    )
                elif stream_delay < 0:
                    input = input.filter("setpts", "PTS-STARTPTS+{-stream_delay}")
                    print(
                        f"Stream {input_info['streamname']} starts after main start: delaying",
                        file=sys.stderr,
                    )
                inputs[input_info["streamname"]] = input
                if has_audio(input_file_info["streams"]):
                    audio = ffmpeg.input(input_info["filename"]).audio
                    if stream_delay > 0:
                        audio_streams.append(
                            audio.filter("atrim", start=stream_delay).filter(
                                "asetpts", "PTS-STARTPTS"
                            )
                        )
                    else:
                        audio_streams.append(
                            audio.filter("setpts", "PTS-STARTPTS+{-stream_delay}")
                        )
            else:
                print(f"Discarding input {input_info['streamname']}")

        size = "{width}:{height}".format(**self.config["output_size"])
        mixed_audio = ffmpeg.filter(audio_streams, "amix", inputs=len(audio_streams))
        in_video = inputs["video-vertical-phone"].filter(
            "scale", size=size, force_original_aspect_ratio="increase"
        )
        return mixed_audio.output(in_video, destination, t=output_duration)


def parse_ts(ts: int) -> DateTime:
    """Returns a Pendulum datetime parsed from the passed datetime from epoch in microseconds."""
    return from_timestamp(ts / 1000 ** 2)


def overlaps(p1: Period, p2: Period) -> bool:
    """Return True if the two passed periods overlap, False otherwise"""
    if p2.start < p1.start < p2.end:
        # p1 starts during p2
        return True
    if p2.start < p1.end < p2.end:
        # p1 ends during p2
        return True
    if p2.start <= p1.start and p2.end >= p1.end:
        # p1 starts before and ends after p2
        return True
    return False


def has_audio(input):
    return any(el.get("channels") for el in input)
