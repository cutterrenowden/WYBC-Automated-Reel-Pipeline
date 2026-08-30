"""reelpipe cli. one subcommand per stage, plus `run` to do the lot."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from . import config as config_mod
from .paths import Job

CLIPBOARD_TOOLS = [["pbcopy"], ["clip.exe"], ["clip"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]


def copy_to_clipboard(text):
    """best effort, returns the tool we used or none."""
    # keep clip.exe from flashing a console window in the windowed app
    no_window = 0x08000000 if os.name == "nt" else 0
    for cmd in CLIPBOARD_TOOLS:
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=text.encode("utf-8"), check=True, creationflags=no_window)
            return cmd[0]
    return None


def build_parser():
    parser = argparse.ArgumentParser(prog="reelpipe", description="cut reels out of long broadcasts")
    parser.add_argument("--config", help="path to a config.toml")
    parser.add_argument("--out-dir", dest="paths_out_dir", help="where job folders live")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check ffmpeg and the asr backend")

    def add_asr_flags(p):
        p.add_argument("--backend", dest="asr_backend", choices=["auto", "mlx", "faster-whisper"])
        p.add_argument("--model", dest="asr_model")
        p.add_argument("--language", dest="asr_language")

    def add_prompt_flags(p):
        p.add_argument("--profile", dest="prompt_profile", choices=["sports", "generic"])
        p.add_argument("--count", dest="clips_count", type=int, help="how many clips to ask for")
        p.add_argument("--min-seconds", dest="clips_min_seconds", type=float)
        p.add_argument("--max-seconds", dest="clips_max_seconds", type=float)
        p.add_argument("--length", dest="clips_target_seconds", type=float, help="rough seconds per clip, the llm decides each one")
        p.add_argument("--energy", dest="energy_enabled", action="store_true", default=None, help="mark loud moments for the llm")

    tr = sub.add_parser("transcribe", help="extract audio, run whisper, write the prompt")
    tr.add_argument("source", help="video or audio file")
    tr.add_argument("--slug", help="job name, defaults to the filename")
    add_asr_flags(tr)
    add_prompt_flags(tr)

    pr = sub.add_parser("prompt", help="rebuild prompt.txt from an existing transcript")
    pr.add_argument("job", help="slug or job folder")
    pr.add_argument("--copy", action="store_true", help="put it on the clipboard")
    add_prompt_flags(pr)

    se = sub.add_parser("select", help="ask an llm api directly instead of pasting")
    se.add_argument("job")
    se.add_argument("--provider", dest="llm_provider", choices=["anthropic", "openai"])
    se.add_argument("--llm-model", dest="llm_model")

    ap = sub.add_parser("apply", help="parse the llm reply, anchor it to word boundaries")
    ap.add_argument("job")
    ap.add_argument("--lead-in", dest="clips_lead_in", type=float)
    ap.add_argument("--lead-out", dest="clips_lead_out", type=float)
    ap.add_argument("--min-seconds", dest="clips_min_seconds", type=float)
    ap.add_argument("--max-seconds", dest="clips_max_seconds", type=float)
    ap.add_argument("--length", dest="clips_target_seconds", type=float, help="rough seconds per clip")

    cu = sub.add_parser("cut", help="render clips + per-clip srt")
    cu.add_argument("job")
    cu.add_argument("--burn-subs", dest="render_burn_subs", action="store_true", default=None)
    cu.add_argument("--vertical", dest="render_vertical", action="store_true", default=None, help="9:16 center-crop")

    ha = sub.add_parser("handoff", help="write the resolve timeline, csv, and report")
    ha.add_argument("job")

    ru = sub.add_parser("run", help="everything end to end")
    ru.add_argument("source")
    ru.add_argument("--slug")
    ru.add_argument("--mode", dest="llm_mode", choices=["manual", "api"])
    ru.add_argument("--burn-subs", dest="render_burn_subs", action="store_true", default=None)
    ru.add_argument("--vertical", dest="render_vertical", action="store_true", default=None, help="9:16 center-crop")
    add_asr_flags(ru)
    add_prompt_flags(ru)

    return parser


def load_config(args):
    cfg = config_mod.load(args.config)
    flags = {k: v for k, v in vars(args).items() if "_" in k and k.split("_")[0] in vars(cfg)}
    return config_mod.override(cfg, **flags)


def show_prompt_hint(job, prompt_paths, copied=None):
    print(f"\nprompt ready: {len(prompt_paths)} file(s)")
    for path in prompt_paths:
        print(f"  {path}")
    if copied:
        print(f"copied to clipboard via {copied}")
    target = "response.txt" if len(prompt_paths) == 1 else "response_01.txt, response_02.txt, ..."
    print(f"paste it into chatgpt/claude, save the reply as {job.root / target}")
    print(f"then: reelpipe apply {job.slug}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = load_config(args)
    from . import pipeline

    if args.command == "doctor":
        return pipeline.doctor(cfg)

    if args.command == "transcribe":
        job = pipeline.ingest(cfg, args.source, args.slug)
        pipeline.transcribe(cfg, job)
        show_prompt_hint(job, pipeline.build_prompt(cfg, job))
        return 0

    if args.command == "prompt":
        job = Job.open(cfg.paths.out_dir, args.job)
        paths = pipeline.build_prompt(cfg, job)
        copied = copy_to_clipboard(paths[0].read_text(encoding="utf-8")) if args.copy else None
        if args.copy and not copied:
            print("no clipboard tool found, copy the file by hand", file=sys.stderr)
        show_prompt_hint(job, paths, copied)
        return 0

    if args.command == "select":
        job = Job.open(cfg.paths.out_dir, args.job)
        pipeline.select_api(cfg, job)
        pipeline.apply_selection(cfg, job)
        return 0

    if args.command == "apply":
        pipeline.apply_selection(cfg, Job.open(cfg.paths.out_dir, args.job))
        return 0

    if args.command == "cut":
        job = Job.open(cfg.paths.out_dir, args.job)
        pipeline.cut(cfg, job)
        pipeline.handoff(cfg, job)
        return 0

    if args.command == "handoff":
        pipeline.handoff(cfg, Job.open(cfg.paths.out_dir, args.job))
        return 0

    if args.command == "run":
        job = pipeline.ingest(cfg, args.source, args.slug)
        pipeline.transcribe(cfg, job)
        paths = pipeline.build_prompt(cfg, job)
        if cfg.llm.mode == "manual":
            show_prompt_hint(job, paths, copy_to_clipboard(paths[0].read_text(encoding="utf-8")))
            return 0
        pipeline.select_api(cfg, job)
        pipeline.apply_selection(cfg, job)
        pipeline.cut(cfg, job)
        pipeline.handoff(cfg, job)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
