from jsonschema import Draft7Validator
from pathlib import Path
from typing import List

import json


SPECS_SCHEMA_JSON = json.loads(
    (Path(__file__).parent / "specs_schema.json").read_text()
)
VALIDATOR = Draft7Validator(SPECS_SCHEMA_JSON)


def validate_specs_schema(specs_text: str) -> List[str]:
    to_validate = json.loads(specs_text)
    return [
        f"{'.'.join(map(str, error.path))}: {error.message}"
        for error in VALIDATOR.iter_errors(to_validate)
    ]
