"""Http server that receives jobs and schedules them on the queue
"""
from pathlib import Path
from probostitcher import Specs
from probostitcher.validation import validate_specs_schema
from probostitcher.worker import get_queue

import bottle
import os
import probostitcher


PORT = os.environ.get("PROBOSTITCHER_SERVER_PORT", 8000)
bottle.TEMPLATE_PATH.append(str(Path(__file__).parent / "templates"))
TEST_FILES_DIR = Path(probostitcher.__file__).parent / "test-files"


@bottle.route("/", method=["POST", "GET"], name="index")
@bottle.view("server")
def index():
    specs_json = bottle.request.forms.get("specs")
    errors = []
    if specs_json:
        errors, specs = validate_specs(specs_json)
        if not errors:
            submit_job(specs)
            message = "Job has been sumbitted. Results will be available "
            message += '<a href="https://google.com">here</a>'
        else:
            message = "Could not process submitted json"
    else:
        specs_json = (TEST_FILES_DIR / "example3-s3.json").read_text()
        message = ""
    return {"specs_json": specs_json, "message": message, "errors": errors}


def validate_specs(specs_json):
    errors, specs = validate_specs_schema(specs_json), None
    if errors:
        return errors, specs
    try:
        specs = Specs(filecontents=specs_json)
    except Exception as e:
        errors.append(str(e))
        return errors, specs
    for chunk in specs:
        try:
            chunk.output("test").compile()
        except Exception as e:
            errors.append(str(e))
    return errors, specs


def submit_job(specs: Specs):
    queue = get_queue()
    queue.send_message(
        MessageBody=specs.filecontents,
        MessageGroupId=specs.output_filename,
        MessageDeduplicationId=specs.output_filename,
    )


def main():
    bottle.run(host="localhost", port=PORT)


if __name__ == "__main__":
    main()
