from pathlib import Path
from videostitcher import Specs


def test_first():
    Specs(Path(__file__).parent / "test-files" / "example.json")
