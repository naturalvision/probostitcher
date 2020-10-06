<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Probostitcher</title>
    <style>
    textarea {
        width: 100%;
        height: auto;
    }
    </style>
  </head>
  <body>
    <h1>Probostitcher</h1>
    <h2>{{! message}}</h2>
    %if video_url:
    <span>
        <video controls width="250">
            <source src="{{ video_url }}" type="video/webm">
            Sorry, your browser doesn't support embedded videos.
        </video>
    </span>
    %end
    <ul>
      %for error in errors:
        <li><pre>{{error}}</pre></li>
      %end
    </ul>
    <form method="POST">
    <textarea name="specs" rows="50">{{specs_json}}</textarea>
    <input type="submit">
    </form>
  </body>
</html>
