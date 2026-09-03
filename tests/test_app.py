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

    def fake_transcribe(cfg, job, **kwargs):
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


def test_bundled_ffmpeg_wins_when_frozen(tmp_path, monkeypatch):
    import sys

    from reelpipe import media

    bindir = tmp_path / "ffmpeg-bin"
    bindir.mkdir()
    fake = bindir / "ffmpeg"
    fake.write_text("")
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert media.find_tool("ffmpeg", "") == str(fake)


def test_uninstall_removes_only_whisper_caches(api, tmp_path, monkeypatch):
    hub = tmp_path / "hfcache" / "hub"
    whisper_model = hub / "models--mlx-community--whisper-tiny"
    whisper_model.mkdir(parents=True)
    (whisper_model / "weights.bin").write_bytes(b"x" * 100)
    (hub / "models--someone--bert").mkdir()
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hfcache"))

    info = api.uninstall_info()
    assert "mlx-community/whisper-tiny" in info["targets"]
    assert info["bytes"] >= 100

    result = api.uninstall()
    assert result["ok"] and "mlx-community/whisper-tiny" in result["removed"]
    assert not whisper_model.exists()
    # a non-whisper model in the same cache is left alone
    assert (hub / "models--someone--bert").exists()
    assert not any("whisper" in t for t in api.uninstall_info()["targets"])


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


def test_burn_captions_after_the_fact(api, tmp_path):
    video = make_video(tmp_path / "late.mp4")
    assert api.start(str(video), {"llm_mode": "manual", "clips_count": 2}) == {"ok": True}
    wait(api)
    slug = events(api, "awaiting")[0]["slug"]
    assert api.submit_responses(slug, [RESPONSE]) == {"ok": True}
    wait(api)
    first = events(api, "done")[0]["results"]
    assert first["burned"] is False
    mp4 = tmp_path / "out" / "video" / slug / "clips" / f"{first['clips'][0]['slug']}.mp4"
    before = mp4.stat().st_mtime

    assert api.burn_captions(slug) == {"ok": True}
    wait(api)
    burned = events(api, "done")[-1]["results"]
    assert burned["burned"] is True
    assert mp4.stat().st_mtime > before

    # fixing subtitle text rewrites the srt, re-burns the clip, and survives recuts
    cues = api.get_subtitles(slug, 1)["cues"]
    texts = [c["text"] for c in cues]
    texts[0] = "HE RISES FROM DEEP"
    before_edit = mp4.stat().st_mtime
    edited = api.set_subtitles(slug, 1, texts)
    assert edited.get("ok"), edited
    srt = mp4.with_suffix(".srt")
    assert "HE RISES FROM DEEP" in srt.read_text(encoding="utf-8")
    assert mp4.stat().st_mtime > before_edit, "burned jobs re-render on subtitle save"

    clip1 = burned["clips"][0]
    assert api.update_clip(slug, 1, clip1["start"], clip1["start"] + 6.0).get("ok")
    assert "HE RISES FROM DEEP" in srt.read_text(encoding="utf-8"), "edits live in the transcript, so recuts keep them"


def test_http_fallback_api(api, tmp_path):
    import json as jsonlib

    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("hi", encoding="utf-8")
    token = "s3cret-token"
    httpd, port = server.start(web, tmp_path / "out", api, token)
    try:
        def post(name, args=None, headers=None, raw=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            hdr = {"Content-Type": "application/json", "X-Reelpipe": token}
            if headers is not None:
                hdr = headers
            conn.request("POST", f"/api/{name}", body=raw if raw is not None else jsonlib.dumps({"args": args or []}), headers=hdr)
            reply = conn.getresponse()
            status, data = reply.status, reply.read()
            conn.close()
            return status, (jsonlib.loads(data) if status == 200 else None)

        # auth: the custom-header token gates every call
        assert post("boot", headers={"Content-Type": "application/json"})[0] == 403
        assert post("boot", headers={"Content-Type": "application/json", "X-Reelpipe": "wrong"})[0] == 403

        status, boot = post("boot")
        assert status == 200 and "doctor" in boot
        assert post("_config")[0] == 404, "private methods stay unreachable"
        assert post("no_such_method")[0] == 404

        # a returned {"error": ...} is 200, a raised exception is 5xx (so the ui rejects it)
        status, body = post("resume", ["nope-does-not-exist"])
        assert status == 500

        # malformed input degrades cleanly, no crash
        assert post("boot", raw="{ not json")[0] == 400

        def get_events(after, tok=token):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", f"/api/events?after={after}", headers={"X-Reelpipe": tok})
            reply = conn.getresponse()
            data = reply.read()
            conn.close()
            return reply.status, data

        assert get_events(0, tok="wrong")[0] == 403
        api._emit("log", line="hello over http")
        status, raw = get_events(0)
        assert status == 200
        evs = jsonlib.loads(raw)["events"]
        assert any(e.get("line") == "hello over http" for e in evs)
        cursor = max(e["seq"] for e in evs)
        assert jsonlib.loads(get_events(cursor)[1])["events"] == []
    finally:
        httpd.shutdown()


def test_preferences_persist_across_boot(api, tmp_path):
    opts = {"llm_mode": "manual", "clips_count": 5, "clips_target_seconds": 45,
            "prompt_profile": "generic", "length_mode": "auto", "render_vertical": True}
    api._save_prefs(opts)
    defaults = api.boot()["defaults"]
    assert defaults["clips_count"] == 5
    assert defaults["clips_target_seconds"] == 45
    assert defaults["prompt_profile"] == "generic"
    assert defaults["length_mode"] == "auto"
    assert defaults["render_vertical"] is True


def test_batch_transcribes_each_file(api, tmp_path):
    a = make_video(tmp_path / "one.mp4")
    b = make_audio(tmp_path / "two.wav")
    assert api.start_batch([str(a), str(b)], {"llm_mode": "manual", "clips_count": 2}) == {"ok": True}
    wait(api)
    assert [e["type"] for e in api.event_log].count("ready") == 2
    done = events(api, "batch_done")
    assert done and done[0]["done"] == 2
    slugs = {j["slug"] for j in api.list_jobs()}
    assert {"one", "two"} <= slugs


def test_vertical_handles_narrow_source(tmp_path):
    from reelpipe.anchor import Clip
    from reelpipe.config import Config
    from reelpipe.cut import cut_clip

    src = tmp_path / "portrait.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=400x1000:rate=30:duration=3", "-f", "lavfi", "-i", "sine=frequency=300:duration=3", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
    cfg = Config()
    cfg.render.preset = "ultrafast"
    dest = tmp_path / "v.mp4"
    cut_clip(cfg, src, Clip(1, "t", 0.0, 2.0), dest, vertical=True, frame=(400, 1000))
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(dest)], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "1080x1920"


def test_transcribe_progress_and_cancel(cfg, tmp_path):
    from reelpipe import transcribe as asr
    from reelpipe.transcript import Segment, Word

    class Seg:
        def __init__(self, s, e, text):
            self.start, self.end, self.text = s, e, text
            self.words = []  # progress/cancel don't depend on word extraction

    class Info:
        duration = 10.0
        language = "en"

    fake = [Seg(0, 2, "a"), Seg(2, 4, "b"), Seg(4, 6, "c")]

    class Model:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, *a, **k):
            return iter(fake), Info()

    import faster_whisper
    seen = []
    # cancel after the second segment
    state = {"n": 0}

    def should_cancel():
        state["n"] += 1
        return state["n"] > 2

    import pytest as _pytest
    orig = faster_whisper.WhisperModel
    faster_whisper.WhisperModel = Model
    try:
        with _pytest.raises(InterruptedError):
            asr._faster_whisper(cfg, tmp_path / "a.wav", "en", duration=10.0, progress=seen.append, should_cancel=should_cancel)
    finally:
        faster_whisper.WhisperModel = orig
    assert seen and seen[0] == 0.2  # 2.0 / 10.0 reported after the first segment


def test_report_url_stays_short(tmp_path):
    from reelpipe.app import diagnostics
    diagnostics.setup(tmp_path / "logs")
    for _ in range(500):
        diagnostics.log("a very long log line to prove the url does not include the whole log " * 3)
    url = diagnostics.report_url()
    assert url.startswith("https://github.com/")
    assert len(url) < 2000, "prefilled issue url must stay under browser url limits"


def test_paste_text_returns_dict(api):
    out = api.paste_text()
    assert isinstance(out, dict) and "text" in out


def test_reframe_pans_the_vertical_crop(api, tmp_path):
    video = make_video(tmp_path / "wide.mp4")
    assert api.start(str(video), {"llm_mode": "manual", "clips_count": 2, "render_vertical": True}) == {"ok": True}
    wait(api)
    slug = events(api, "awaiting")[0]["slug"]
    assert api.submit_responses(slug, [RESPONSE]) == {"ok": True}
    wait(api)
    results = events(api, "done")[-1]["results"]
    assert all(c["vertical"] for c in results["clips"])
    idx = results["clips"][0]["index"]

    frame = api.reframe_frame(slug, idx)
    assert frame.get("ok") and 0 < frame["box_w"] < 1  # wide source pans horizontally

    out = api.reframe_clip(slug, idx, 0.0)   # hard left
    assert out.get("ok"), out
    assert out["clip"]["crop_x"] == 0.0
    mp4 = tmp_path / "out" / "video" / slug / "clips" / f"{out['clip']['slug']}.mp4"
    dims = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(mp4)], capture_output=True, text=True, check=True)
    assert dims.stdout.strip() == "1080x1920", "still a valid vertical clip after panning"

    # crop_x persists in clips.json and survives a reload
    from reelpipe import anchor
    saved = anchor.load(tmp_path / "out" / "video" / slug / "clips.json")
    assert next(c for c in saved if c.index == idx).crop_x == 0.0
