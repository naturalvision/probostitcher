from ffmpeg.nodes import FilterableStream
from pathlib import Path
from pendulum import DateTime
from pendulum import Period
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional

import ffmpeg
import json
import os
import sys
import tempfile


class Specs:
    """Represents a JSON file and accompanying video/audio files.
    Instantiate passing the JSON file path as the only argument to `__init__`.
    """

    #: A dictionary read (and slightly augmented/changed) from the config file
    config: Dict
    #: A dictionary containing info about input track files, extracted from self.config["inputs"]
    inputs: Dict[str, Dict[str, str]]
    #: A dictionary containing ffmpeg analysis of the given input
    inputs_infos: Dict[str, Dict]
    #: Pendulum Period indicating the time span the output should show
    output_period: Period
    #: Chunks that will make up the final video
    video_chunks: List[FilterableStream]
    #: The audio track of the output
    audio_track: FilterableStream
    #: If True debug infos will be printed out during conversion
    debug: bool

    def __init__(self, filepath: str, debug=False):
        self.filepath = Path(filepath)
        self.debug = debug
        with open(filepath) as fh:
            self.config = json.load(fh)
        output_start = parse_ts(int(self.config["output_start"]))
        output_end = output_start.add(seconds=self.config["output_duration"])
        self.width, self.height = (
            self.config["output_size"]["width"],
            self.config["output_size"]["height"],
        )
        self.inputs = {el["streamname"]: el for el in self.config["inputs"]}
        self.output_period = output_end - output_start
        self.analyze_files()
        self.prepare_chunks()
        self.prepare_audio_track()

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
                period = Period(start=self.ts(start), end=self.ts(end))
                track = self.trim_to_chunk(video_specs["streamname"], period)
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
                    track = track.filter("setpts", "PTS-STARTPTS")
                    chunk = chunk.overlay(track, x=x, y=y)
            self.video_chunks.append(chunk)

    def trim_to_chunk(self, streamname: str, period: Period) -> FilterableStream:
        """Trim the given streamname to match the given Period.
        Black screen will be introduced if the given period is not fully covered by the given input.
        """
        filename = self.absolute_path(self.inputs[streamname]["filename"])
        input = ffmpeg.input(filename)
        input_info = self.input_infos[streamname]
        input_period = get_input_period(input_info)
        width = input_info["streams"][0]["width"]
        height = input_info["streams"][0]["height"]
        if input_period.start < period.start:
            # We need to trim our input: it starts earlier than needed
            input = input.trim(
                start=duration(period.start - input_period.start)
            ).filter("setpts", "PTS-STARTPTS")
        elif input_period.start > period.start:
            # We need to add black to the beginning
            padding_duration = input_period.start - period.start
            padding_duration = duration(padding_duration)
            padding = (
                ffmpeg.source("testsrc", s=f"{width}x{height}")
                .trim(end=f"{padding_duration:f}")
                .filter("reverse")
            )
            input = ffmpeg.concat(padding, input)

        if input_period.end > period.end:
            # We need to trim the input: it ends past our desired point in time
            input = input.trim(end=duration(period))
        elif input_period.end < period.end:
            # TODO: We need to append padding to the end of the video
            # otherwise the last frame will be repeated
            pass
        fps = self.config.get("output_framerate", 25)
        return input.filter("fps", fps)

    def print(self, message: str):
        if self.debug:
            print(message, file=sys.stderr)

    def analyze_files(self):
        """Run ffprobe on all inputs and store the information in self.infos"""
        self.input_infos = {}
        for input_info in self.config["inputs"]:
            # Convert file paths to absolute in case they're relative
            # TODO we can support HTTP URLs by prepending async:cache
            # see https://ffmpeg.org/ffmpeg-protocols.html#async
            input_info["filename"] = self.absolute_path(input_info["filename"])
            self.print(f"Analyzing {input_info['filename']}")
            # Use ffprobe to get more info about streams
            input_file_info = ffmpeg.probe(input_info["filename"])
            self.input_infos[input_info["streamname"]] = input_file_info

    def prepare_audio_track(self):
        audio_streams = []
        for input_specs in self.config["inputs"]:
            input_info = self.input_infos[input_specs["streamname"]]
            input_period = get_input_period(input_info)
            if overlaps(self.output_period, input_period):
                if has_audio(input_info["streams"]):
                    audio_streams.append(
                        adjust_audio_track(input_specs, input_info, self.output_period)
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
        """Render the final video in the file specified by `destination`.
        First renders all chunks. Then concatenates the chunks and mixes in audio.
        """
        final_video_path = get_tmp_path()
        rendered_chunks = self.render_videos(final_video_path)
        video = ffmpeg.concat(*map(ffmpeg.input, rendered_chunks))
        final = self.audio_track.output(
            video, destination, t=self.output_period.in_seconds()
        )
        final.run()

    def render_videos(self, destination: str) -> List[str]:
        """Render the video chunks as specced, saving it to temporary files and returning them."""
        rendered_chunks = []
        base_filename = get_tmp_path("")
        for i, chunk in enumerate(self.video_chunks):
            filename = base_filename + f"-chunk{i}.webm"
            rendered_chunks.append(filename)
            todo = chunk.output(
                filename,
                vsync="cfr",  # Frames will be duplicated and dropped to achieve exactly the requested constant frame rate
                copytb=1,  # Use the demuxer timebase.
            )
            todo.run()
        return rendered_chunks

    def __len__(self) -> int:
        """Returns the number of chunks for this specs"""
        return len(self.video_chunks)

    def __iter__(self) -> Iterator:
        return iter(self.video_chunks)

    def __get__(self, index: int) -> FilterableStream:
        """Returns an OutputStream object representing the chunk identified by `index`."""
        return self.video_chunks[index]

    def ts(self, seconds: int) -> DateTime:
        """Convert a value in seconds to a DateTime object.
        Uses the output_start as t0.
        """
        return DateTime.fromtimestamp(
            (self.config["output_start"] + seconds * 1000 ** 2) / 1000 ** 2
        )


def duration(period: Period) -> float:
    """GIven a moment period, return a float representing its duration in (fractional) seconds"""
    return (period.in_seconds() * 1000 ** 2 + period.microseconds) / 1000 ** 2


def get_input_start(input_file_info: Dict) -> int:
    """Given a dict as returned by ffprobe, return the start time in microseconds since Epoch"""
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
        start_from_comment_s = json.loads(info_from_stream_comment[0])["u"]
    else:
        # Get the input from the "format" key
        start_from_comment_s = json.loads(input_file_info["format"]["tags"]["COMMENT"])[
            "u"
        ]
    return int(start_from_comment_s)


def get_input_period(input_file_info: Dict) -> Period:
    start = DateTime.fromtimestamp(get_input_start(input_file_info) / 1000 ** 2)
    end = start.add(seconds=float(input_file_info["format"]["duration"]))
    return Period(start=start, end=end)


def scale_to(input, width, height):
    """Scale the given video and add black bands to make it exactly the desired size"""
    return input.filter(
        "scale",
        size=f"{width}:{height}",
        force_original_aspect_ratio="decrease",
    ).filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2")


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
        input = input.filter("trim", start=stream_delay)
    elif stream_delay < 0:
        # We should add black frames for `stream_delay` time: first we create the video to prepend
        intro = scale_to(
            ffmpeg.source("testsrc").trim(end=abs(stream_delay)), width, height
        ).filter("reverse")
        input = ffmpeg.concat(intro, scale_to(input, width, height))
    return input


def adjust_audio_track(
    input_specs: Dict, input_info: Dict, output_period: Period
) -> FilterableStream:
    """Adjust an audio track to match desired output times"""
    stream_delay = (
        output_period.start.timestamp() - get_input_start(input_info) / 1000 ** 2
    )
    audio = ffmpeg.input(input_specs["filename"]).audio
    if stream_delay > 0:
        return audio.filter("atrim", start=stream_delay).filter(
            "asetpts", "PTS-STARTPTS"
        )
    else:
        intro = ffmpeg.source("anullsrc").filter("atrim", duration=abs(stream_delay))
        return ffmpeg.concat(intro, audio, v=0, a=1).filter("asetpts", "PTS-STARTPTS")


def parse_ts(ts: int) -> DateTime:
    """Returns a Pendulum datetime parsed from the passed datetime from epoch in microseconds."""
    return DateTime.fromtimestamp(ts / 1000 ** 2)


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


def get_tmp_path(extension=".webm"):
    fh, tmp_path = tempfile.mkstemp(extension)
    os.fdopen(fh).close()
    os.unlink(tmp_path)
    return tmp_path
