from ffmpeg.nodes import FilterableStream
from ffmpeg.nodes import OutputStream
from pathlib import Path
from pendulum import DateTime
from pendulum import from_timestamp
from pendulum import Period
from typing import Dict
from typing import List
from typing import Optional

import ffmpeg
import json
import re
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
    video_tracks: Dict[str, FilterableStream]
    #: Chunks that will make up the final video
    video_chunks: List[FilterableStream]
    #: The audio track of the output
    audio_track: FilterableStream

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        with open(filepath) as fh:
            self.config = json.load(fh)
        output_start = parse_ts(int(self.config["output_start"]))
        output_end = output_start.add(seconds=self.config["output_duration"])
        self.width, self.height = (
            self.config["output_size"]["width"],
            self.config["output_size"]["height"],
        )
        self.output_period = output_end - output_start
        self.prepare_tracks()
        self.prepare_chunks()

    def prepare_chunks(self):
        assert self.config["milestones"][0]["timestamp"] == 0
        self.video_chunks = []
        howmany = len(self.config["milestones"])
        default_width, default_height = (
            self.config["output_size"]["width"],
            self.config["output_size"]["height"],
        )
        for i in range(howmany):
            # Prepare chunk i
            milestone = self.config["milestones"][i]
            is_last = i == howmany - 1
            if is_last:  # This is the last milestone
                end = self.config["output_duration"]
            else:
                end = self.config["milestones"][i + 1]["timestamp"]
            start = milestone["timestamp"]
            chunk = None
            for video_specs in milestone["videos"]:
                # Trim/resize the videos of this chunk
                track = self.video_tracks[video_specs["streamname"]]
                if not is_last:
                    # If some later milestones exist they will want a copy of this track
                    # So we split it, use one of the split result and store the other for later use
                    split_track = track.split()
                    track = split_track[0]
                    self.video_tracks[video_specs["streamname"]] = split_track[1]
                track = track.trim(start=start, end=end).filter(
                    "setpts", "PTS-STARTPTS"
                )

                # Resize the video
                width, height = (
                    video_specs.get("width", default_width),
                    video_specs.get("height", default_height),
                )
                track = scale_to(track, width, height)
                # Overlay it over what we have so far
                if chunk is None:
                    chunk = track
                else:
                    x, y = video_specs.get("x", 0), video_specs.get("y", 0)
                    chunk = chunk.overlay(track, x=x, y=y)
            self.video_chunks.append(chunk)

    def prepare_tracks(self):
        """Prepare the input tracks needed to assemble the output.
        Store the result in self.video_tracks and self.audio_track.
        The audio track is final. The video tracks will be used to assemble chunks.
        """
        self.video_tracks = {}
        audio_streams = []
        for input_info in self.config["inputs"]:
            # Convert file paths to absolute in case they're relative
            # TODO we can support HTTP URLs by prepending async:cache
            # see https://ffmpeg.org/ffmpeg-protocols.html#async
            input_info["filename"] = self.absolute_path(input_info["filename"])
            print(f"Analyzing {input_info['filename']}", file=sys.stderr)
            # Use ffprobe to get more info about streams
            input_file_info = ffmpeg.probe(input_info["filename"])
            if "start" not in input_info:
                info_from_stream_comment = [
                    el["tags"]["COMMENT"]
                    for el in input_file_info["streams"]
                    if "COMMENT" in el.get("tags", {})
                ]
                info_from_stream_comment = info_from_stream_comment or [
                    el["tags"]["comment"]
                    for el in input_file_info["streams"]
                    if "comment" in el.get("tags", {})
                ]
                if info_from_stream_comment:
                    input_info["start_from_comment_u"] = json.loads(
                        info_from_stream_comment[0]
                    )["u"]
                    input_info["start_from_comment_s"] = json.loads(
                        info_from_stream_comment[0]
                    )["s"]
                else:
                    # Get the input from the "format" key
                    input_info["start_from_comment_u"] = json.loads(
                        input_file_info["format"]["tags"]["COMMENT"]
                    )["u"]
                    input_info["start_from_comment_s"] = json.loads(
                        input_file_info["format"]["tags"]["COMMENT"]
                    )["s"]
                input_info["start_from_filename"] = int(
                    re.match(
                        ".*-([0-9]*)(-(audio|video))?.(webm|opus)",
                        input_info["filename"],
                    ).groups()[0]
                )
                input_info["start"] = input_info["start_from_comment_s"]
                input_info["start"] = input_info["start_from_filename"]
                input_info["start"] = input_info["start_from_comment_u"]
            input_start = parse_ts(input_info["start"])
            input_duration = float(input_file_info["format"]["duration"])
            input_end = input_start.add(seconds=input_duration)
            input_period = input_end - input_start
            if overlaps(self.output_period, input_period):
                if has_video(input_file_info):
                    width, height = [
                        (el["width"], el["height"])
                        for el in input_file_info["streams"]
                        if "width" in el
                    ][0]
                    adjusted_video = adjust_video_track(
                        input_info, self.output_period, self.width, self.height
                    )
                    self.video_tracks[input_info["streamname"]] = adjusted_video

                if has_audio(input_file_info["streams"]):
                    audio_streams.append(
                        adjust_audio_track(input_info, self.output_period)
                    )
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
        # in_video = self._combine_tracks_hstack()  # Uncomment to debug and see all videos side by side
        in_video = ffmpeg.concat(*self.video_chunks)
        fps = self.config.get("output_framerate", 25)
        return self.audio_track.output(
            in_video.filter("fps", fps),
            destination,
            t=self.output_period.in_seconds(),
            vsync="cfr",  # Frames will be duplicated and dropped to achieve exactly the requested constant frame rate
            copytb=1,  # Use the demuxer timebase.
        )

    def _combine_tracks_hstack(self):
        """Utility/debug function to get all tracks next to each other using the hstack filter"""
        width, height = (
            self.config["output_size"]["width"],
            self.config["output_size"]["height"],
        )
        size = "{width}:{height}".format(**self.config["output_size"])

        def scale_video(video):
            return video.filter(
                "scale",
                size=size,
                force_original_aspect_ratio="decrease",
            ).filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2")

        return ffmpeg.filter(
            list(map(scale_video, self.video_tracks.values())),
            "hstack",
            inputs=len(self.video_tracks),
        )


def scale_to(input, width, height):
    """Scale the given video and add black bands to make it exactly the desired size"""
    return (
        input.filter(
            "scale",
            size=f"{width}:{height}",
            force_original_aspect_ratio="decrease",
        )
        .filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2")
        .filter("setsar", "1", "1")
    )


def adjust_video_track(
    input_info: Dict[str, str], output_period: Period, width: int, height: int
) -> FilterableStream:
    """Adjust a track so that it has the same duration as the output period.
    Size is needed to create black padding video of the right size"""
    # stream_delay is the length of time between the start of this stream and te start of the output
    # A positive value means this input should be trimmed, and starts as the output starts.
    # A negative value means this input should be delayed, and starts at a later point than the main output.
    stream_delay = (
        output_period.start - parse_ts(int(input_info["start"]))
    ).in_seconds()
    input = ffmpeg.input(input_info["filename"])
    video_begin = int(input_info["start"]) / 1000 ** 2
    # Burn in timecode
    input = input.filter(
        "drawtext",
        fontfile="FreeSerif.ttf",
        fontcolor="white",
        text="%{pts:gmtime:" + str(video_begin) + "}",
        fontsize="20",
    )
    if stream_delay > 0:
        input = input.filter("trim", start=stream_delay).filter(
            "setpts", "PTS-STARTPTS"
        )
    elif stream_delay < 0:
        # We should add black frames for `stream_delay` time: first we create the video to prepend
        intro = scale_to(
            ffmpeg.source("testsrc").trim(end=abs(stream_delay)), width, height
        ).filter("reverse")
        input = ffmpeg.concat(intro, scale_to(input, width, height))
        input = input.filter("setpts", "PTS-STARTPTS")
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
        intro = ffmpeg.source("anullsrc").filter("atrim", duration=abs(stream_delay))
        return ffmpeg.concat(intro, audio, v=0, a=1).filter("asetpts", "PTS-STARTPTS")


def parse_ts(ts: int) -> DateTime:
    """Returns a Pendulum datetime parsed from the passed datetime from epoch in microseconds."""
    return from_timestamp(ts / 1000 ** 2)


def overlaps(p1: Period, p2: Period) -> Optional[Period]:
    """Return the overlapping period of the given ones.
    If there is no overlap return None"""
    start = max(p1.start, p2.start)
    end = min(p1.end, p2.end)
    if end < start:
        return None
    return Period(start=start, end=end)


def has_audio(input):
    return any(el.get("channels") for el in input)


def has_video(input):
    return any(el.get("coded_width") for el in input["streams"])
