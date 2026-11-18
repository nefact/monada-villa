"""Premium style: beat-grid edit with motivated transitions, film finish and animated serif typography."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .common import BUILD, OUT, ROOT, SHOT_INDEX, load_yaml, read_csv, resolve_facts, run, settings
from .render import ass_time, make_cover, srt_time
from .trend import FPS, H, W, photo_clip, video_clip

TMP = BUILD / "tmp_premium"
FONTS = ROOT / "fonts"
# xfade transitions used at a junction; durations are short so the cut still lands on the beat
TRANS = {"cut": ("fade", 0.04), "whip": ("smoothleft", 0.28), "whipr": ("smoothright", 0.28), "zoom": ("zoomin", 0.35),
         "blur": ("hblur", 0.30), "fade": ("fade", 0.45), "up": ("smoothup", 0.28)}
GRADE = ("eq=contrast=1.05:saturation=0.94:gamma=0.98,colorbalance=rs=0.03:gs=0.01:bs=-0.03:rh=0.03:bh=-0.02,"
         "curves=master='0/0.03 0.5/0.5 1/0.97'")
FINISH = "vignette=angle=PI/6,noise=alls=5:allf=t+u"

ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: serif,MonadaSerif,112,&H00FFFFFF,&H00FFFFFF,&H64000000,&H00000000,0,1,0,0,100,100,0,0,1,4,0,5,70,70,0,1
Style: serifbig,MonadaSerif,150,&H00FFFFFF,&H00FFFFFF,&H64000000,&H00000000,0,1,0,0,100,100,0,0,1,4,0,5,60,60,0,1
Style: caps,Inter Medium,44,&H00FFFFFF,&H00FFFFFF,&H64000000,&H00000000,0,0,0,0,100,100,9,0,1,3,0,5,70,70,0,1
Style: brand,MonadaSerif,128,&H00FFFFFF,&H00FFFFFF,&H64000000,&H00000000,0,0,0,0,100,100,34,0,1,3,0,5,60,60,0,1
Style: num,MonadaSerif,440,&H00FFFFFF,&H00FFFFFF,&H64000000,&H00000000,0,1,0,0,100,100,0,0,1,4,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ev(a: float, b: float, style: str, text: str, y: int, rise: int = 26) -> str:
    fx = rf"{{\an5\blur8\fad(380,220)\move(540,{y + rise},540,{y},0,520)}}"
    return f"Dialogue: 0,{ass_time(a)},{ass_time(b)},{style},,0,0,0,,{fx}{text.replace(chr(10), chr(92) + 'N')}\n"


def render_premium(p: dict, bpm: int, archive: Path, idx: dict) -> dict:
    beat = 60 / bpm
    tdir = TMP / p["id"]
    if tdir.exists():
        shutil.rmtree(tdir)
    tdir.mkdir(parents=True)
    clips = p["clips"]
    durs = [c["beats"] * beat for c in clips]
    # each clip is rendered long enough to cover the overlap of the transition into the next clip
    tr_in = [TRANS[c.get("trans", "cut")] for c in clips]
    outs, sources, events, srt = [], [], [], []
    for i, c in enumerate(clips):
        s = idx[c["shot"]]
        over = tr_in[i + 1][1] if i + 1 < len(clips) else 0
        dur = durs[i] + over
        out = tdir / f"{i:02d}.mp4"
        focus = float(c.get("focus", 0.5))
        if s["type"] == "photo":
            photo_clip(archive / s["file"], dur, c.get("motion", "push"), focus, out, GRADE)
            sources.append({"shot_id": s["shot_id"], "file": s["file"], "t_in": 0, "dur": round(dur, 2)})
        else:
            sp = float(c.get("speed", 1.0))
            a, b = float(s["t_in"]), float(s["t_out"])
            t0 = a + max(0.0, (b - a) - dur * sp) * float(c.get("at", 0.5))
            video_clip(archive / s["file"], t0, dur, sp, focus, out, GRADE)
            sources.append({"shot_id": s["shot_id"], "file": s["file"], "t_in": round(t0, 2), "dur": round(dur * sp, 2)})
        outs.append(out)
    starts = [sum(durs[:i]) for i in range(len(durs))]
    total = sum(durs)
    for i, c in enumerate(clips):
        for t in c.get("texts", []):
            txt, _ = resolve_facts(t["text"])
            a = starts[i] + t.get("at", 0.1)
            b = starts[i] + t.get("until", durs[i] - 0.05) if "until" in t else starts[i] + durs[i] - 0.05
            b = starts[i] + t["until"] if "until" in t else b
            events.append((a, b, t.get("style", "serif"), txt, int(t.get("y", 820))))
    lines = [ASS_HEAD] + [ev(a, b, st, txt, y) for a, b, st, txt, y in sorted(events)]
    (tdir / "subs.ass").write_text("".join(lines), encoding="utf-8")
    for k, (a, b, st, txt, y) in enumerate(sorted(events), 1):
        srt.append(f"{k}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n")
    # transition chain
    ins = sum((["-i", str(o)] for o in outs), [])
    fc, last = [], "[0:v]"
    for i in range(1, len(outs)):
        name, d = tr_in[i]
        fc.append(f"{last}[{i}:v]xfade=transition={name}:duration={d}:offset={starts[i]:.3f}[x{i}]")
        last = f"[x{i}]"
    fc.append(f"{last}{FINISH},subtitles=filename=subs.ass:fontsdir={FONTS}[v]")
    music = p.get("music")
    if music:
        mp = ROOT / "music" / "preview" / music
        a_in = ["-i", str(mp)]
        mstart = float(p.get("music_start", 0))
        fc.append(f"[{len(outs)}:a]atrim={mstart}:{mstart + total},asetpts=PTS-STARTPTS,afade=t=in:d=0.4,"
                  f"afade=t=out:st={max(0, total - 1.2):.2f}:d=1.2,loudnorm=I=-14:TP=-1.5[a]")
    else:
        a_in = ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        fc.append(f"[{len(outs)}:a]anull[a]")
    odir = OUT / "premium"
    odir.mkdir(parents=True, exist_ok=True)
    mp4 = (odir / f"{p['id']}_{p['name']}.mp4").resolve()
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *ins, *a_in, "-filter_complex", ";".join(fc),
         "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "slow", "-crf", "17",
         "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(mp4)], cwd=tdir)
    cover_title = resolve_facts(p.get("cover", p["name"]))[0]
    make_cover(outs[0], min(0.8, durs[0] / 2), cover_title, odir / f"{p['id']}_{p['name']}_COVER.jpg", settings())
    (odir / f"{p['id']}_{p['name']}.srt").write_text("\n".join(srt), encoding="utf-8")
    meta = {"id": p["id"], "concept": p.get("concept", ""), "duration": round(total, 2), "shots": len(outs),
            "sources": sources, "music": music or "none (add in Instagram)"}
    (odir / f"{p['id']}_{p['name']}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    shutil.rmtree(tdir, ignore_errors=True)
    return meta


def render_premium_all(archive: Path, only: list[str] | None = None) -> None:
    data = load_yaml("premium_prototypes.yaml")
    idx = {r["shot_id"]: r for r in read_csv(SHOT_INDEX)}
    for p in data["prototypes"]:
        if only and p["id"] not in only:
            continue
        m = render_premium(p, p.get("bpm", data.get("bpm", 100)), archive, idx)
        print(f"✓ {p['id']} {p['name']}: {m['duration']}s, {m['shots']} shots", flush=True)
