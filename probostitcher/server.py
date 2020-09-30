"""Http server that receives jobs and schedules them on the queue
"""
from pathlib import Path

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
    if specs_json:
        message = "Job has been sumbitted. Results will be available "
        message += '<a href="https://google.com">here</a>'
    else:
        specs_json = (TEST_FILES_DIR / "example3-s3.json").read_text()
        message = ""
    return {"specs_json": specs_json, "message": message}


def main():
    bottle.run(host="localhost", port=PORT)


if __name__ == "__main__":
    main()
