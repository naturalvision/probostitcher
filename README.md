# Stitch Janus created videos

## Setup

- Setup `direnv` on your machine

- Create a `.envrc-secret` file and put AWS credentials and config there:

  ```bash
  export AWS_SECRET_ACCESS_KEY=YYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY
  export AWS_ACCESS_KEY_ID=XXXXXXXXXXXXXXXXXXXX
  export PROBOSTITCHER_OUTPUT_BUCKET=probostitcher
  export PROBOSTITCHER_REGION=eu-central-1
  export PROBOSTITCHER_QUEUE_NAME=probostitcher.fifo
  export PROBOSTITCHER_QUEUE_REGION=eu-west-2
  ```

- Install

  ```bash
  pip install -e .
  ```

## Running

Run the probostitcher http server:

  ```bash
  probostitcher
  ```

In a different terminal, run

  ```bash
  probostitcher-worker
  ```

Open http://localhost:8000/ on your browser.

You'll be presented a form to submit your specs file.  Please find
examples of spec files in `probostitcher/test-files/*json`.

If an error is found in the JSON specs, it will be shown on form
submission.

Upon successful submission, a job will be submitted to the SQS queue,
and the worker process will use ffmpeg to render the final video. The
final video will be then uploaded to S3.

The form will display the video as soon as it's rendered (it polls
every two seconds to see if the video is done).
