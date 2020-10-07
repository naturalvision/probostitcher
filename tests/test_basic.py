from pathlib import Path
from probostitcher import Specs
from probostitcher.specs import parse_ts

import json
import os
import probostitcher
import pytest


CREATE_VIDEO = os.environ.get("CREATE_VIDEO") is not None
UPLOAD_VIDEO = os.environ.get("UPLOAD_VIDEO") is not None

TEST_FILES_DIR = Path(probostitcher.__file__).parent / "test-files"


def disabled_test_start_offsets():
    """Not really a test, but a utility to view the differences between timestamps"""
    from rich.console import Console
    from rich.table import Table

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Stream name", style="dim")
    table.add_column("Comment S")
    table.add_column("Comment U")
    table.add_column("Filename")

    specs = Specs(TEST_FILES_DIR / "example3.json")
    for input in specs.config["inputs"]:
        start_from_comment_s = parse_ts(input["start_from_comment_s"])
        start_from_comment_u = parse_ts(input["start_from_comment_u"])
        start_from_filename = parse_ts(input["start_from_filename"])
        table.add_row(
            input["streamname"],
            start_from_comment_s.to_time_string(),
            start_from_comment_u.to_time_string(),
            start_from_filename.to_time_string(),
        )
    print()
    Console().print(table)


S3_EXAMPLES = []
# Include S3 examples only if AWS credentials are set up
if "AWS_SECRET_ACCESS_KEY" in os.environ:
    S3_EXAMPLES.append("example3-s3.json")


@pytest.mark.parametrize(
    "json_filename", ["example.json", "example2.json", "example3.json"] + S3_EXAMPLES
)
def test_video_generation(json_filename):
    specs = Specs(
        TEST_FILES_DIR / json_filename,
        debug=True,
        cleanup=False,
        parallelism=4,
    )
    for chunk in specs:
        chunk.output("test").compile()  # Smoke test

    tmp_path = f"/tmp/{specs.output_filename}"
    if CREATE_VIDEO:
        specs.render(tmp_path)
        print(f"Written file {tmp_path}")

    if UPLOAD_VIDEO:
        specs.upload(tmp_path)


def test_validation():
    from probostitcher.validation import validate_specs_schema

    good_one_text = (TEST_FILES_DIR / "example3.json").read_text()
    assert validate_specs_schema(good_one_text) == []

    bad_one = json.loads(good_one_text)
    del bad_one["inputs"]
    assert validate_specs_schema(json.dumps(bad_one)) == [
        ": 'inputs' is a required property"
    ]

    bad_one = json.loads(good_one_text)
    bad_one["inputs"] = []
    assert validate_specs_schema(json.dumps(bad_one)) == ["inputs: [] is too short"]

    bad_one = json.loads(good_one_text)
    del bad_one["output_size"]["width"]
    del bad_one["output_duration"]
    assert validate_specs_schema(json.dumps(bad_one)) == [
        "output_size: 'width' is a required property",
        ": 'output_duration' is a required property",
    ]
