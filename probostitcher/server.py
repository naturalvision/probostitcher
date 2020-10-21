"""Http server that receives jobs and schedules them on the queue
"""
from pathlib import Path
from probostitcher import Specs
from probostitcher.s3 import create_presigned_url
from probostitcher.s3 import OUTPUT_BUCKET
from probostitcher.validation import validate_specs_schema
from probostitcher.worker import get_queue
from probostitcher.worker import QUEUE_NAME
from probostitcher.worker import QUEUE_REGION

import bottle
import json
import os
import probostitcher
import uuid


PORT = os.environ.get("PROBOSTITCHER_SERVER_PORT", 8000)
bottle.TEMPLATE_PATH.append(str(Path(__file__).parent / "templates"))
TEST_FILES_DIR = Path(probostitcher.__file__).parent / "test-files"
STATIC_FILES_ROOT = Path(probostitcher.__file__).parent / "static"


@bottle.route("/", method=["POST", "GET"], name="index")
@bottle.view("server")
def index():
    specs_json = bottle.request.forms.get("specs")
    errors = []
    video_url = ""
    if specs_json:
        errors, specs = validate_specs(specs_json)
        if not errors:
            submit_job(specs)
            video_url = create_presigned_url(
                f"s3://{OUTPUT_BUCKET}/output/{specs.output_filename}", expiration=86400
            )
            message = "Job has been sumbitted. Results will be available "
            message += f'<a href="{video_url}">here</a>'
        else:
            message = "Could not process submitted json"
    else:
        specs_json = (TEST_FILES_DIR / "example3-s3.json").read_text()
        message = ""
    return {
        "specs_json": specs_json,
        "message": message,
        "errors": errors,
        "video_url": video_url,
        "json": json,
    }


@bottle.route("/static/<filename>")
def server_static(filename):
    return bottle.static_file(filename, root=STATIC_FILES_ROOT)


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
        MessageGroupId=uuid.uuid4().hex,
        # MessageGroupId=specs.output_filename,
        # Maybe we should reconsider this: we use the hash of the specs to prevent message
        # duplication; it means we won't be able to resubmit the very same job twice.
        # We comment it out for now, to be able to repeatedly test the same specs
        # MessageDeduplicationId=specs.output_filename,
        # But we need to provide a value, since without it we get the error:
        # The queue should either have ContentBasedDeduplication enabled or MessageDeduplicationId provided explicitly
        MessageDeduplicationId=uuid.uuid4().hex,
    )
    print(f"Submitted job to queue {QUEUE_NAME} in {QUEUE_REGION}")


def main():
    bottle.run(host="localhost", port=PORT)


if __name__ == "__main__":
    main()
