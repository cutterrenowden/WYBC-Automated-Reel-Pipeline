"""headless checks on the desktop app: the bridge drives a real job end to end
(whisper stubbed, ffmpeg real) and the little media server behaves."""

import http.client
import shutil
import subprocess

import pytest

from reelpipe import pipeline
from reelpipe.app import server
from reelpipe.app.bridge import Api

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs ffmpeg")

RESPONSE = """```json
[
  {"title": "The Shot", "start_quote": "he pulls up from thirty feet", "end_quote": "it is good", "approx_start": "0:07", "score": 9, "caption": "cold blooded", "hashtags": ["#hoops"]},
  {"title": "Timeout", "start_quote": "timeout on the floor", "end_quote": "settle things down", "approx_start": "0:18", "score": 6}
]
```"""


def make_video(path, seconds=26):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=30:duration={seconds}", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


@pytest.fixture
def api(tmp_path, transcript, monkeypatch):
    (tmp_path / "config.toml").write_text("[clips]\nmin_seconds = 4.0\nmax_seconds = 20.0\nlead_in = 0.5\nlead_out = 0.5\n\n[render]\npreset = \"ultrafast\"\n", encoding="utf-8")

    def fake_transcribe(cfg, job):
        transcript.source = str(job.source)
        transcript.save(job.transcript_json)
        job.write_meta({"asr": {"backend": "stub", "model": "stub", "language": "en"}, "words": len(transcript.words())})
        return transcript

    monkeypatch.setattr(pipeline, "transcribe", fake_transcribe)
    return Api(tmp_path)


def wait(api):
    api._thread.join(timeout=180)
    assert not api._thread.is_alive()


def events(api, kind):
    return [event for event in api.event_log if event["type"] == kind]


def test_manual_flow_with_splice_fixes(api, tmp_path):
    video = make_video(tmp_path / "game.mp4")

    assert api.start(str(video), {"llm_mode": "manual", "clips_count": 2, "render_burn_subs": True}) == {"ok": True}
    wait(api)
    awaiting = events(api, "awaiting")
    assert awaiting, [e for e in api.event_log if e["type"] == "error"]
    assert "start_quote" in awaiting[0]["prompts"][0]
    slug = awaiting[0]["slug"]

    # a garbage paste is rejected up front, nothing runs
    assert "error" in api.submit_responses(slug, ["not json at all"])
    assert "error" in api.check_response("nope")
    assert api.check_response(RESPONSE)["picks"] == 2

    assert api.submit_responses(slug, [RESPONSE]) == {"ok": True}
    wait(api)
    done = events(api, "done")
    assert done, [e for e in api.event_log if e["type"] == "error"]
    results = done[0]["results"]
    assert [clip["title"] for clip in results["clips"]] == ["The Shot", "Timeout"]
    assert all(clip["rendered"] and clip["kind"] == "video" for clip in results["clips"])
    for clip in results["clips"]:
        assert clip["poster"], "every rendered clip gets a first-frame thumbnail"
        assert (tmp_path / "out" / "video" / slug / "clips" / f".thumb_{clip['slug']}.jpg").is_file()
    assert "REPORT.md" in results["handoff"]
    assert "reels.xml" in results["handoff"]

    # the app can find its way back to this job later
    assert api.resume(slug)["status"] == "done"
    assert api.list_jobs()[0]["status"] == "done"

    # splice fix: force clip 1 to exactly five seconds and re-render it
    first = results["clips"][0]
    fixed = api.update_clip(slug, 1, first["start"], first["start"] + 5.0)
    assert fixed.get("ok"), fixed
    assert fixed["clip"]["duration"] == pytest.approx(5.0)
    assert "manually adjusted" in fixed["clip"]["warnings"]
    mp4 = tmp_path / "out" / "video" / slug / "clips" / f"{first['slug']}.mp4"
    assert probe_duration(mp4) == pytest.approx(5.0, abs=0.35)

    # nonsense edits are refused
    assert "error" in api.update_clip(slug, 1, 10.0, 10.2)
    assert "error" in api.update_clip(slug, 99, 0, 5)

    # the adjust editor gets a padded preview around the clip
    preview = api.make_preview(slug, 1, 4)
    assert preview.get("ok"), preview
    assert preview["window_start"] <= fixed["clip"]["start"]
    preview_file = tmp_path / "out" / "video" / slug / "clips" / ".preview_01.mp4"
    assert preview_file.is_file()
    assert probe_duration(preview_file) == pytest.approx(preview["window_end"] - preview["window_start"], abs=0.4)
    assert "error" in api.make_preview(slug, 99)

    # deleting drops the files and the report keeps going
    gone = api.delete_clip(slug, 2)
    assert gone.get("ok"), gone
    assert len(gone["results"]["clips"]) == 1
    assert not (tmp_path / "out" / "video" / slug / "clips" / "02_timeout.mp4").exists()


def make_audio(path, seconds=26):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", str(path)], check=True)
    return path


def test_inspect_accepts_video_and_audio_rejects_the_rest(api, tmp_path):
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    assert "only video or audio" in api.inspect(str(tmp_path / "notes.txt"))["error"]
    assert api.inspect(str(make_audio(tmp_path / "pod.wav", seconds=2)))["has_video"] is False
    assert api.inspect(str(make_video(tmp_path / "game.mp4", seconds=2)))["has_video"] is True


def test_audio_job_cuts_m4a_clips(api, tmp_path):
    audio = make_audio(tmp_path / "podcast.wav")
    assert api.start(str(audio), {"llm_mode": "manual", "clips_count": 2}) == {"ok": True}
    wait(api)
    awaiting = events(api, "awaiting")
    assert awaiting, [e for e in api.event_log if e["type"] == "error"]
    slug = awaiting[0]["slug"]

    assert api.submit_responses(slug, [RESPONSE]) == {"ok": True}
    wait(api)
    done = events(api, "done")
    assert done, [e for e in api.event_log if e["type"] == "error"]
    results = done[0]["results"]
    assert results["root"].endswith(f"audio/{slug}")
    for clip in results["clips"]:
        assert clip["kind"] == "audio" and clip["ext"] == ".m4a" and clip["rendered"]
        assert clip["poster"] is None
    m4a = tmp_path / "out" / "audio" / slug / "clips" / f"{results['clips'][0]['slug']}.m4a"
    assert probe_duration(m4a) == pytest.approx(results["clips"][0]["duration"], abs=0.35)
    assert api.list_jobs()[0]["kind"] == "audio"

    # splice fixes and previews work without a video track
    fixed = api.update_clip(slug, 1, results["clips"][0]["start"], results["clips"][0]["start"] + 5.0)
    assert fixed.get("ok"), fixed
    assert fixed["clip"]["kind"] == "audio"
    assert probe_duration(m4a) == pytest.approx(5.0, abs=0.35)
    assert api.make_preview(slug, 1, 3).get("ok")


def test_api_mode_refuses_without_a_key(api, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = api.start(str(tmp_path / "whatever.mp4"), {"llm_mode": "api", "llm_provider": "anthropic"})
    assert "ANTHROPIC_API_KEY" in out["error"]


def test_uninstall_removes_only_whisper_caches(api, tmp_path, monkeypatch):
    hub = tmp_path / "hfcache" / "hub"
    whisper_model = hub / "models--mlx-community--whisper-tiny"
    whisper_model.mkdir(parents=True)
    (whisper_model / "weights.bin").write_bytes(b"x" * 100)
    (hub / "models--someone--bert").mkdir()
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hfcache"))

    info = api.uninstall_info()
    assert info["targets"] == ["mlx-community/whisper-tiny"]
    assert info["bytes"] >= 100

    result = api.uninstall()
    assert result["ok"] and result["removed"] == ["mlx-community/whisper-tiny"]
    assert not whisper_model.exists()
    assert (hub / "models--someone--bert").exists()
    assert api.uninstall_info()["targets"] == []


def test_ui_prefs_roundtrip_and_uninstall_includes_them(api, tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "empty-hf"))
    assert api.boot()["ui"] == {}
    api.set_ui({"dark": True, "junk": "ignored"})
    assert api.boot()["ui"] == {"dark": True}
    assert ".reelpipe-ui.json" in api.uninstall_info()["targets"]
    assert api.uninstall()["ok"]
    assert api.boot()["ui"] == {}


def test_media_server_ranges_and_traversal(tmp_path):
    web = tmp_path / "web"
    jobs = tmp_path / "jobs"
    web.mkdir(), jobs.mkdir()
    (web / "index.html").write_text("<html>hi</html>", encoding="utf-8")
    (jobs / "clip.bin").write_bytes(bytes(range(100)))
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    httpd, port = server.start(web, jobs)
    try:
        def get(path, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", path, headers=headers or {})
            reply = conn.getresponse()
            body = reply.read()
            conn.close()
            return reply, body

        reply, body = get("/app/")
        assert reply.status == 200 and b"hi" in body

        reply, body = get("/jobs/clip.bin", {"Range": "bytes=10-19"})
        assert reply.status == 206
        assert body == bytes(range(10, 20))
        assert reply.getheader("Content-Range") == "bytes 10-19/100"

        reply, _ = get("/jobs/clip.bin", {"Range": "bytes=500-"})
        assert reply.status == 416

        reply, _ = get("/jobs/../secret.txt")
        assert reply.status == 404
        reply, _ = get("/elsewhere/x")
        assert reply.status == 404
    finally:
        httpd.shutdown()
