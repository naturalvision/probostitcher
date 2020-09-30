from botocore.client import Config
from botocore.exceptions import ClientError
from ffmpeg.nodes import FilterableStream
from hashlib import sha512
from multiprocessing import Pool
from pathlib import Path
from pendulum import DateTime
from pendulum import Period
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional
from urllib.parse import urlparse

import boto3
import ffmpeg
import json
import logging
import os
import shlex
import subprocess
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
    #: Path to the directory where temporary files are stored
    tmp_dir: Path
    #: Number of ffmpeg processes to run in parallel
    parallelism: int

    _output_filename: Optional[str] = None

    def __init__(
        self,
        filepath: str,
        debug: bool = False,
        cleanup: bool = True,
        parallelism: int = len(os.sched_getaffinity(0)),
    ):
        self.filepath = Path(filepath)
        self.debug = debug
        self.parallelism = parallelism
        with open(filepath) as fh:
            self.config = json.load(fh)
        output_start = parse_ts(int(self.config["output_start"]))
        output_end = output_start.add(seconds=self.config["output_duration"])
        self._presign_s3_urls()
        self.width, self.height = (
            self.config["output_size"]["width"],
            self.config["output_size"]["height"],
        )
        self.inputs = {el["streamname"]: el for el in self.config["inputs"]}
        self.output_period = output_end - output_start
        self._analyze_files()
        self._prepare_chunks()
        self._prepare_audio_track()
        if cleanup:
            self.__tmp_dir = tempfile.TemporaryDirectory(prefix="probostitcher-")
            self._tmp_dir = Path(self.__tmp_dir.name)
        else:
            self._tmp_dir = Path(tempfile.mkdtemp(prefix="probostitcher-"))

    @property
    def output_filename(self):
        """The output filename is hashed from this file contents and specs contents.
        This way we can make sure to not compile the same video twice.
        """
        if self._output_filename is None:
            specs_file_contents = open(self.filepath).read().encode("utf-8")
            specs_file_hash = self._output_filename = sha512(
                specs_file_contents
            ).hexdigest()
            this_file_contents = open(__file__).read().encode("utf-8")
            this_file_hash = self._output_filename = sha512(
                this_file_contents
            ).hexdigest()
            self._output_filename = f"{this_file_hash[:4]}-{specs_file_hash[:12]}.webm"
            self._output_filename = f"{specs_file_hash[:12]}.webm"
        return self._output_filename

    def _prepare_chunks(self):
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
                track = self.trim_to_period(video_specs["streamname"], period)
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
            if self.debug:
                video_begin = self.config["output_start"] / 1000 ** 2
                video_begin += milestone["timestamp"]
                chunk = chunk.filter(
                    "drawtext",
                    fontfile="FreeSans.ttf",
                    fontcolor="white",
                    shadowcolor="black",
                    shadowx="1",
                    shadowy="2",
                    text="%{pts:gmtime:" + str(video_begin) + "}",
                    fontsize="20",
                    x="0",
                    y="h-th",
                )
            self.video_chunks.append(chunk)

    def trim_to_period(self, streamname: str, period: Period) -> FilterableStream:
        """Trim the given streamname to match the given Period.
        Black screen will be introduced if the given period is not fully covered by the given input.
        """
        filename = self.absolute_path(self.inputs[streamname]["filename"])
        input = ffmpeg.input(filename)
        input_info = self.input_infos[streamname]
        input_period = get_input_period(input_info)

        width = input_info["streams"][0]["width"]
        height = input_info["streams"][0]["height"]
        size = f"{width}x{height}"
        # XXX This will possibly unnecessarily downscale a video
        # It's necessary because the size ffprobe reports is the one detected at the start of the video
        # Ideally we should check all frame sizes and use the biggest one here
        # That we instead of losing precious information (image detail) we would be wasting some CPU cycles
        input = input.filter(
            "scale",
            size=f"{width}:{height}",
            force_original_aspect_ratio="decrease",
        )

        if self.debug:
            # Add timestamp at the top
            video_begin = input_period.start.timestamp()
            input = input.filter(
                "drawtext",
                fontfile="FreeSerif.ttf",
                fontcolor="white",
                shadowcolor="black",
                shadowx="1",
                shadowy="2",
                text="%{pts:gmtime:" + str(video_begin) + "}",
                fontsize="20",
            )

        if input_period.start < period.start:
            # We need to trim our input: it starts earlier than needed
            input = input.trim(
                start=duration(period.start - input_period.start)
            ).filter("setpts", "PTS-STARTPTS")
        elif input_period.start > period.start:
            # We need to add black to the beginning
            padding_duration = input_period.start - period.start
            padding_duration = duration(padding_duration)
            padding = ffmpeg.source(
                "testsrc", size=size, duration=f"{padding_duration:f}"
            ).filter("reverse")
            input = ffmpeg.concat(padding, input)

        if input_period.end > period.end:
            # We need to trim the input: it ends past our desired point in time
            input = input.trim(end=duration(period))
        elif input_period.end < period.end:
            # TODO: We need to append padding to the end of the video
            # otherwise the last frame will be repeated
            after_padding_period = period.end - input_period.end
            after_padding_duration = (
                after_padding_period.in_seconds()
                + after_padding_period.microseconds / 1000 ** 2
            )
            after_padding = ffmpeg.source(
                "color", color="black", size=size, duration=after_padding_duration
            )
            input = input.concat(after_padding)
        fps = self.config.get("output_framerate", 25)
        return input.filter("fps", fps)

    def print(self, message: str):
        if self.debug:
            print(message, file=sys.stderr)

    def _analyze_files(self):
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

    def _prepare_audio_track(self):
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
        if filename.startswith("http") or filename.startswith("/"):
            return filename
        return str(self.filepath.parent / filename)

    def render(self, destination: Optional[str] = None):
        """Render the final video in the file specified by `destination`.
        If omitted, renders in the temporary directory.
        First renders all chunks. Then concatenates the chunks and mixes in audio.
        """
        if destination is None:
            destination = str(self._tmp_dir / self.output_filename)
        if os.path.isfile(destination):
            self.print("Not rendering {destination}: file exists")
            return
        final_video_path = str(self._tmp_dir / "final.webm")
        self.render_videos(final_video_path)
        txt_filename = str(self._tmp_dir / "chunk-list.txt")
        with open(txt_filename, "w") as fh:
            for i in range(len(self.video_chunks)):
                fh.write(f"file {self._tmp_dir}/chunk-'{i}.webm'\n")
        command = [
            "ffmpeg",
            "-safe",
            "0",
            "-f",
            "concat",
            "-i",
            txt_filename,
            "-c",
            "copy",
            final_video_path,
        ]
        self.print(subprocess.check_output(command).decode("utf-8"))
        video = ffmpeg.input(final_video_path)
        final = self.audio_track.output(
            video, destination, t=self.output_period.in_seconds(), vcodec="copy"
        )
        final.run()

    def render_videos(self, destination: str):
        """Render the video chunks as specced, saving it to temporary files and returning them."""
        base_filename = self._tmp_dir / "chunk-"
        pool = Pool(self.parallelism)

        commands = []
        for i, chunk in enumerate(self.video_chunks):
            filename = str(base_filename) + f"{i}.webm"
            todo = chunk.output(
                filename,
                vsync="cfr",  # Frames will be duplicated and dropped to achieve exactly the requested constant frame rate
                copytb=1,  # Use the demuxer timebase.
            )
            commands.append(todo.compile())
        result = pool.map(run_ffmpeg, commands)
        # TODO: check if any process errored out and collect error message
        self.print(repr(result))

    def upload(self, rendered_video_path: Optional[str] = None):
        """Upload the final video to S3. If the file does not exist the video
        will be rendered first.
        """
        if rendered_video_path is None:
            rendered_video_path = str(self._tmp_dir / self.output_filename)
        if not os.path.exists(rendered_video_path):
            self.render(rendered_video_path)
        bucket = os.environ["PROBOSTITCHER_OUTPUT_BUCKET"]

        try:
            get_boto_client().upload_file(
                rendered_video_path, bucket, self.output_filename
            )
        except ClientError as e:
            logging.error(e)
            raise

    def _presign_s3_urls(self):
        for input in self.config["inputs"]:
            if input["filename"].startswith("s3://"):
                input["filename"] = create_presigned_url(input["filename"])

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


def get_boto_client():
    region = os.environ["PROBOSTITCHER_REGION"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://s3.{region}.amazonaws.com",
        config=Config(signature_version="s3v4", region_name=region),
    )


def create_presigned_url(url: str, expiration: int = 3600) -> str:
    """Generate a presigned URL to share an S3 object"""
    parsed_url = urlparse(url)
    try:
        response = get_boto_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": parsed_url.netloc,
                "Key": parsed_url.path[1:],
            },
            ExpiresIn=expiration,
        )
    except ClientError as e:
        logging.error(e)
        raise
    # The response contains the presigned URL
    return response


def run_ffmpeg(args: List[str]):
    """Function to be invoked in a subprocess to in turn invoke ffmpeg."""
    print("Running: ")
    print(" ".join(map(shlex.quote, args)))
    return subprocess.check_output(args)


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
    """Given an ffprobe generated info dict, return a Period object."""
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
