"""v2 trend-format renderer: hard cuts on a beat grid, punchy photo zooms, sped-up walks, big hooks, labels, loop."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image, ImageOps

from .common import BUILD, OUT, ROOT, load_yaml, read_csv, resolve_facts, run, settings, SHOT_INDEX
from .render import ass_time, make_cover, srt_time

TMP = BUILD / "tmp_trend"
W, H, FPS = 1080, 1920, 30


def photo_clip(src: Path, dur: float, motion: str, focus: float, out: Path, grade: str) -> None:
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    # crop to 9:16 around focus, then 2x size so zoompan stays smooth
    tw = min(im.width, round(im.height * 9 / 16))
    th = min(im.height, round(im.width * 16 / 9))
    x = int((im.width - tw) * focus)
    im = im.crop((x, (im.height - th) // 2, x + tw, (im.height - th) // 2 + th)).resize((W * 2, H * 2), Image.LANCZOS)
    big = out.with_suffix(".src.jpg")
    im.save(big, quality=95)
    n = max(1, round(dur * FPS))
    z = {"push": f"1+0.14*on/{n}", "pull": f"1.32-0.32*on/{n}", "none": "1.0"}.get(motion, "1+0.08*on/" + str(n))
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(big), "-vf",
         f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS},{grade},setsar=1,format=yuv420p",
         "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", str(out)])


def video_clip(src: Path, t0: float, dur: float, speed: float, focus: float, out: Path, grade: str) -> None:
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t0:.3f}", "-t", f"{dur * speed + 0.1:.3f}", "-i", str(src),
         "-an", "-vf", f"setpts=PTS/{speed},scale={W}:{H}:force_original_aspect_ratio=increase,"
         f"crop={W}:{H}:x='(iw-{W})*{focus}':y='(ih-{H})/2',{grade},fps={FPS},setsar=1,format=yuv420p",
         "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", str(out)])


ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: hook,Inter Bold,92,&H00FFFFFF,&H00FFFFFF,&H50000000,&H00000000,0,0,0,0,100,100,0,0,1,5,0,8,80,80,430,1
Style: sub,Inter Medium,38,&H00FFFFFF,&H00FFFFFF,&H50000000,&H00000000,0,0,0,0,100,100,8,0,1,4,0,8,80,80,600,1
Style: label,Inter Bold,66,&H00FFFFFF,&H00FFFFFF,&H50000000,&H00000000,0,0,0,0,100,100,0,0,1,5,0,2,80,80,520,1
Style: brand,Inter ExtraLight,96,&H00FFFFFF,&H00FFFFFF,&H50000000,&H00000000,0,0,0,0,100,100,22,0,1,4,0,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def temp_beat(total: float, bpm: int) -> list[str]:
    """Placeholder groove for review only (replace with an Instagram library track at upload)."""
    b = 60 / bpm
    kick = f"0.9*sin(2*PI*(48+90*exp(-28*mod(t,{b})))*mod(t,{b}))*exp(-8*mod(t,{b}))"
    hat = f"0.18*(random(0)*2-1)*exp(-70*mod(t+{b / 2},{b}))"
    pad = "+".join(f"0.05*sin(2*PI*{f}*t)" for f in (110, 164.81, 220, 277.18))
    return ["-f", "lavfi", "-t", f"{total:.3f}", "-i", f"aevalsrc='{kick}+{hat}+{pad}':s=48000:c=stereo"]


def render_proto(p: dict, bpm: int, archive: Path, idx: dict, cfg: dict) -> dict:
    grade = cfg["render"]["grade"] + ",eq=contrast=1.06:saturation=1.08"
    beat = 60 / bpm
    tdir = TMP / p["id"]
    if tdir.exists():
        shutil.rmtree(tdir)
    tdir.mkdir(parents=True)
    clips, events, srt, t, sources = [], [], [], 0.0, []
    for i, c in enumerate(p["clips"]):
        s = idx[c["shot"]]
        dur = c["beats"] * beat
        out = tdir / f"{i:02d}.mp4"
        focus = float(c.get("focus", 0.5))
        if s["type"] == "photo":
            photo_clip(archive / s["file"], dur, c.get("motion", "push"), focus, out, grade)
            sources.append({"shot_id": s["shot_id"], "file": s["file"], "t_in": 0, "dur": dur})
        else:
            sp = float(c.get("speed", 1.0))
            a, b = float(s["t_in"]), float(s["t_out"])
            need = dur * sp
            t0 = a + max(0.0, (b - a) - need) * float(c.get("at", 0.5))
            video_clip(archive / s["file"], t0, dur, sp, focus, out, grade)
            sources.append({"shot_id": s["shot_id"], "file": s["file"], "t_in": round(t0, 2), "dur": round(need, 2)})
        clips.append(out)
        if c.get("label"):
            txt, _ = resolve_facts(c["label"])
            st = c.get("label_style", "label")
            events.append((t + (0.05 if st == "label" else 0.25), t + dur - 0.02, st, txt))
        t += dur
    total = t
    hook, _ = resolve_facts(p.get("hook", ""))
    if hook:
        events.insert(0, (0.0, min(2.6, total), "hook", hook))
    if p.get("sub"):
        events.insert(1, (0.0, min(2.6, total), "sub", p["sub"]))
    ass = tdir / "subs.ass"
    lines = [ASS_HEAD]
    for k, (a, b, st, txt) in enumerate(events, 1):
        fx = r"{\blur6\fad(0,150)}" if st != "brand" else r"{\blur6\fad(250,0)}"
        lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},{st},,0,0,0,,{fx}{txt.replace(chr(10), chr(92) + 'N')}\n")
        srt.append(f"{k}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n")
    ass.write_text("".join(lines), encoding="utf-8")
    ins = sum((["-i", str(c)] for c in clips), [])
    n = len(clips)
    graph = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[cat];[cat]subtitles=filename=subs.ass[v];" \
            f"[{n}:a]highpass=f=35,lowpass=f=9000,afade=t=in:d=0.05,afade=t=out:st={max(0, total - 0.6):.2f}:d=0.6," \
            f"loudnorm=I=-14:TP=-1.5:LRA=7[a]"
    odir = OUT / "trend"
    odir.mkdir(parents=True, exist_ok=True)
    mp4 = (odir / f"{p['id']}_{p['name']}.mp4").resolve()
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *ins, *temp_beat(total, bpm), "-filter_complex", graph,
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(mp4)], cwd=tdir)
    make_cover(clips[0], min(0.6, total / 2), hook.replace("\n", " ") or p["name"], odir / f"{p['id']}_{p['name']}_COVER.jpg", cfg)
    (odir / f"{p['id']}_{p['name']}.srt").write_text("\n".join(srt), encoding="utf-8")
    meta = {"id": p["id"], "format": p["format"], "duration": round(total, 2), "cuts": n, "avg_shot_s": round(total / n, 2),
            "sources": sources, "audio": "TEMP generated 120 BPM beat — replace with an Instagram library track"}
    (odir / f"{p['id']}_{p['name']}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    shutil.rmtree(tdir, ignore_errors=True)
    return meta


def render_trends(archive: Path, only: list[str] | None = None) -> None:
    cfg = settings()
    data = load_yaml("trend_prototypes.yaml")
    idx = {r["shot_id"]: r for r in read_csv(SHOT_INDEX)}
    for p in data["prototypes"]:
        if only and p["id"] not in only:
            continue
        m = render_proto(p, data.get("bpm", 120), archive, idx, cfg)
        print(f"✓ {p['id']} {p['name']}: {m['duration']}s, {m['cuts']} cuts, avg {m['avg_shot_s']}s/shot", flush=True)
