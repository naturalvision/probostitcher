from ffmpeg.nodes import FilterableStream
from ffmpeg.nodes import OutputStream
from pathlib import Path
from pendulum import DateTime
from pendulum import from_timestamp
from pendulum import Period
from typing import Dict

import ffmpeg
import json
import sys


class Specs:
    """Represents a JSON file and accompanying video/audio files.
    Instantiate passing the JSON file path as the only argument to `__init__`.
    """

    #: A dictionary read (and slightly augmented/changed) from the config file
    config: Dict
    #: Pendulum Period indicating the time span the output should show
    output_period: Period
    #: Tracks needed to assemble the output
    tracks: Dict[str, FilterableStream]
    #: The audio track of the output
    audio_track: FilterableStream

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        with open(filepath) as fh:
            self.config = json.load(fh)
        output_start = parse_ts(int(self.config["output_start"]))
        output_end = output_start.add(seconds=self.config["output_duration"])
        self.output_period = output_end - output_start
        self.prepare_inputs()

    def prepare_inputs(self):
        """Prepare the input tracks needed to assemble the output.
        Store the result in self.tracks
        """
        self.tracks = {}
        self.inputs = {}
        for input_info in self.config["inputs"]:
            # Convert file paths to absolute in case they're relative
            # TODO we can support HTTP URLs by prepending async:cache
            # see https://ffmpeg.org/ffmpeg-protocols.html#async
            input_info["filename"] = self.absolute_path(input_info["filename"])
            print(f"Analyzing {input_info['filename']}", file=sys.stderr)
            # Use ffprobe to get more info about streams
            input_file_info = ffmpeg.probe(input_info["filename"])

            input_start = parse_ts(int(input_info["start"]))
            input_duration = float(input_file_info["format"]["duration"])
            input_end = input_start.add(seconds=input_duration)
            input_period = input_end - input_start
            audio_streams = []
            if overlaps(self.output_period, input_period):
                self.tracks[input_info["streamname"]] = adjust_track(
                    input_info, self.output_period
                )
            if has_audio(input_file_info["streams"]):
                audio_streams.append(adjust_audio_track(input_info, self.output_period))
        self.audio_track = ffmpeg.filter(
            audio_streams, "amix", inputs=len(audio_streams)
        )

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
        size = "{width}:{height}".format(**self.config["output_size"])
        in_video = self.tracks["video-vertical-phone"].filter(
            "scale", size=size, force_original_aspect_ratio="increase"
        )
        return self.audio_track.output(
            in_video, destination, t=self.output_period.in_seconds()
        )


def adjust_track(input_info: Dict[str, str], output_period: Period) -> FilterableStream:
    """Adjust a track so that it has the same duration as the output period"""
    # stream_delay is the length of time between the start of this stream and te start of the output
    # A positive value means this input should be trimmed, and starts as the output starts.
    # A negative value means this input should be delayed, and starts at a later point than the main output.
    stream_delay = (
        output_period.start - parse_ts(int(input_info["start"]))
    ).in_seconds()
    input = ffmpeg.input(input_info["filename"])
    if stream_delay > 0:
        input = input.filter("trim", start=stream_delay).filter(
            "setpts", "PTS-STARTPTS"
        )
    elif stream_delay < 0:
        input = input.filter("setpts", "PTS-STARTPTS+{-stream_delay}")
    return input


def adjust_audio_track(
    input_info: Dict[str, str], output_period: Period
) -> FilterableStream:
    """Adjust an audio track to match desired output times"""
    stream_delay = (
        output_period.start - parse_ts(int(input_info["start"]))
    ).in_seconds()
    audio = ffmpeg.input(input_info["filename"]).audio
    if stream_delay > 0:
        return audio.filter("atrim", start=stream_delay).filter(
            "asetpts", "PTS-STARTPTS"
        )
    else:
        return audio.filter("setpts", "PTS-STARTPTS+{-stream_delay}")


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
