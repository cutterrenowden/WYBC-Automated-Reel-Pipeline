# ReelPipe

ReelPipe is a desktop app designed for Yale's WYBC Radio Station that automates converting podcasts or sport footage with broadcast audio into spliced sections for use on social media, namely Instagram Reels. You can upload a MP4 or MP3, and ReelPipe will automatically transcribe the audio using an included multimodal transcription model included in the installer. Then, the application uses AI to find the best moments to insert cuts. You can choose to have ReelPipe burn the subtitles into the video, or output the respective subtitle track files for you to manipulate in your favorite video editor, along with other customizable options.


## Install

1. Download the app from the [latest release](https://github.com/cutterrenowden/WYBC-Automated-Reel-Pipeline/releases/latest): `ReelPipe-macOS.dmg` or `ReelPipe-Windows-Setup.exe`, depending on your machine.
2. Install ffmpeg: `brew install ffmpeg` on macOS, `winget install Gyan.FFmpeg` on Windows before running the application to satisfy dependencies. If this step does not work, restart the application.
3. macOS only: the app is unsigned, so right-click and Open the first time.

## Use

Drop a file into the app. Pick clip count and length. Copy the prompt into ChatGPT or Claude and
paste the reply back. Preview the clips, customize the start and end of each clip, and delete the videos if desired. Files are outputted to designated folder.

In Resolve: import `handoff/reels.xml`, set the timeline vertical, reframe, drop the SRTs on a
subtitle track.

Example in [example/](example/).


