function schedule_check_video() {
  check_video();
}

function check_video() {
  fetch(VIDEO_URL, { headers: { Range: "bytes=0-20" } })
    .then(function (response) {
      if (response.status !== 206) {
        setTimeout(check_video, 2000);
        return;
      }
      var video_element = document.getElementsByTagName("video")[0];
      video_element.innerHTML =
        '<source src="' + VIDEO_URL + '" type="video/webm"></source>';
    })
    .catch(function () {
      console.error("Error trying to fetch video");
    });
}
