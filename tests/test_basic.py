from pathlib import Path
from probostitcher import Specs
from probostitcher.specs import parse_ts

import os
import pytest
import tempfile


CREATE_VIDEO = False
CREATE_VIDEO = True


def disabled_test_start_offsets():
    """Not really a test, but a utility to view the differences between timestamps"""
    from rich.console import Console
    from rich.table import Table

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Stream name", style="dim")
    table.add_column("Comment S")
    table.add_column("Comment U")
    table.add_column("Filename")

    specs = Specs(Path(__file__).parent / "test-files" / "example3.json")
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


@pytest.mark.parametrize(
    "json_filename", ["example.json", "example2.json", "example3.json"]
)
def test_video_generation(json_filename):
    specs = Specs(
        Path(__file__).parent / "test-files" / json_filename, debug=True, cleanup=False
    )
    if CREATE_VIDEO:
        tmp_path = get_tmp_path()
        specs.render(tmp_path)
        print(f"Written file {tmp_path}")


def get_tmp_path():
    fh, tmp_path = tempfile.mkstemp(".webm")
    os.fdopen(fh).close()
    os.unlink(tmp_path)
    return tmp_path
