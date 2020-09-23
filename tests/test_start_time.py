"""Our source material files come with a start time as microseconds from Epoch.
Often more than one value is provided, and after experimenting we determined
which of them is the one we're after.
These test make sure the code that extracts the value is robust.
"""
from start_time_cases import CASES

import pytest


@pytest.mark.parametrize(
    "data,expected_result", [(el["data"], el["expected_result"]) for el in CASES]
)
def test_start_time(data, expected_result):
    from probostitcher.specs import get_input_start

    assert get_input_start(data) == expected_result
