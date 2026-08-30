# ReelPipe for WYBC

ReelPipe is a desktop app designed for Yale's WYBC Radio Station that automates converting podcasts or sport footage with broadcast audio into spliced sections for use on social media, namely Instagram Reels. You can upload a MP4 or MP3, and ReelPipe will automatically transcribe the audio using a multimodal transcription model included in the installer. Then, the application uses AI to find the best moments to insert cuts. You can choose to have ReelPipe burn the subtitles into the video, or output the respective subtitle track files for you to manipulate in your favorite video editor, along with other customizable options.

## Install

1. Download the app from the [latest release](https://github.com/cutterrenowden/WYBC-Automated-Reel-Pipeline/releases/latest): `ReelPipe-macOS.dmg` or `ReelPipe-Windows-Setup.exe`, depending on your machine.
2. macOS only: the app is unsigned, so you may need to manually approve it opening. Attempt to open the application. Then, after the error, open up System Settings -> Privacy & Security, and open it there. You only need to do this the first time.
3. Windows only: the app is unsigned, so you may need to manually approve it opening. In the downloads section of your browser, right click on the application, and press "keep". A pop-up will open -- on the bottom right, click on the carat next to the delete button, and press "keep anyway". 

## Use

Drop a file into the app. Pick clip count and length. Copy the prompt into ChatGPT or Claude and paste the reply back, or use an API key. Preview the clips, customize the start and end of each clip, modify subtitles, and delete the videos if desired. Files are outputted to designated folder. 

Example and walkthrough in [example/](example/).

<img width="1156" height="771" alt="Screenshot 2026-08-27 at 4 49 09 PM" src="https://github.com/user-attachments/assets/03e7ace8-28e9-408f-8af0-9a3b00ad6e5c" />

<img width="1156" height="767" alt="Screenshot 2026-08-27 at 4 49 29 PM" src="https://github.com/user-attachments/assets/4fe20437-2fb3-4ad9-888d-ae5e23652ec9" />

