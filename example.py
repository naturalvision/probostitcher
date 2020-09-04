#!/usr/bin/env python
from pendulum import from_timestamp
from pendulum import Pendulum
from pendulum import Period

import ffmpeg
import json
import sys


class Specs:
    def __init__(self, filepath):
        with open(filepath) as fh:
            self.config = json.load(fh)
        self.inputs = {}
        for fileinfo in self.config["inputs"]:
            print(f"Analyzing {fileinfo['filename']}", file=sys.stderr)
            self.inputs[fileinfo["streamname"]] = ffmpeg.probe(fileinfo["filename"])


def parse_ts(ts: int) -> Pendulum:
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


if __name__ == "__main__":
    specs = Specs("example.json")
    output_start = parse_ts(int(specs.config["output_start"]))
    output_duration = specs.config["output_duration"]
    output_end = output_start.add(seconds=output_duration)
    output_period = output_end - output_start
    inputs = {}
    audio_streams = []
    for input_info in specs.config["inputs"]:
        input_start = parse_ts(int(input_info["start"]))
        input_file_info = specs.inputs[input_info["streamname"]]
        input_duration = float(input_file_info["format"]["duration"])
        input_end = input_start.add(seconds=input_duration)
        input_period = input_end - input_start

        # Only append this to the inputs if it contributes to the final video.
        if overlaps(output_period, input_period):
            # stream_delay is the length of time between the start of this stream and te start of the output
            # A positive value means this input should be trimmed, and starts as the output starts.
            # A negative value means this input should be delayed, and starts at a later point than the main output.
            stream_delay = (output_start - parse_ts(input_info["start"])).in_seconds()
            input = ffmpeg.input(input_info["filename"])
            if stream_delay > 0:
                input = input.filter("trim", start=stream_delay).filter(
                    "setpts", "PTS-STARTPTS"
                )
                print(
                    "Stream {input_info['streamname']} starts before main start: trimming"
                )
            elif stream_delay < 0:
                input = input.filter("setpts", "PTS-STARTPTS+{-stream_delay}")
                print(
                    "Stream {input_info['streamname']} starts after main start: delaying"
                )
            inputs[input_info["streamname"]] = input
            if has_audio(input_file_info["streams"]):
                audio_streams.append(ffmpeg.input(input_info["filename"]).audio)
        else:
            print(f"Discarding input {input_info['streamname']}")

    size = "{}:{}".format(*specs.config["output_size"])
    mixed_audio = ffmpeg.filter(audio_streams, "amix", inputs=len(audio_streams))
    in_video = inputs["video-vertical-phone"].filter(
        "scale", size=size, force_original_aspect_ratio="increase"
    )
    out, _ = (
        mixed_audio.output(in_video, "out.mp4", t=output_duration)
        .overwrite_output()
        .run()
    )
