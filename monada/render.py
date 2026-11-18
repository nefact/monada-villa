"""Steps 6–7: render specs → 1080x1920 H.264 MP4 + cover + SRT + QA, and carousels → 1080x1350 JPG."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .common import BUILD, OUT, ROOT, ffprobe, load_yaml, run, settings

SPECS = BUILD / "specs"
TMP = BUILD / "tmp"
LICENSED = ROOT / "music" / "licensed"


# ───────── helpers ─────────
def hex_to_ass(c: str, alpha: str = "00") -> str:
    c = c.lstrip("#")
    return f"&H{alpha}{c[4:6]}{c[2:4]}{c[0:2]}"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Resolve a family name ('Inter Light', 'WenQuanYi Zen Hei') or file name via fontconfig."""
    cands = [name]
    try:
        path = run(["fc-match", "-f", "%{file}", name]).stdout.strip()
        if path:
            cands.insert(0, path)
    except Exception:
        pass
    for cand in cands + ["DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    return ImageFont.load_default()


def prep_photo(src: Path, dst: Path, max_side: int = 2600) -> Path:
    """Apply EXIF orientation and downsize once, so ffmpeg loops a light, correctly rotated image."""
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, quality=95)
    return dst


def is_dark(lighting: str) -> bool:
    return any(k in (lighting or "") for k in ("night", "evening"))


# ───────── per-shot clip ─────────
def shot_clip(sh: dict, archive: Path, out: Path, cfg: dict, natural_audio: bool) -> Path:
    r = cfg["render"]
    W, H, fps, dur = r["width"], r["height"], r["fps"], sh["dur"]
    src = archive / sh["file"]
    bg = r["frame_bg_dark"] if is_dark(sh["lighting"]) else r["frame_bg_light"]
    grade = r["grade"]
    fx = min(max(sh.get("focus_x", 0.5), 0.0), 1.0)
    inputs: list[str] = []
    if sh["type"] == "photo":
        src = prep_photo(src, out.with_suffix(".src.jpg"))
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(src)]
    else:
        inputs += ["-ss", f"{sh['t_in']:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
    inputs += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]

    if sh["fit"] == "cover":
        if sh["type"] == "photo":
            a, b = (max(0, fx - 0.06), min(1, fx + 0.06))
            if sh.get("motion") == "pan_left":
                a, b = b, a
            v = (f"[0:v]scale={int(W * 1.08)}:{int(H * 1.08)}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H}:x='(iw-{W})*({a:.3f}+({b - a:.3f})*t/{dur:.3f})':y='(ih-{H})/2'")
        else:
            v = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H}:x='(iw-{W})*{fx:.3f}':y='(ih-{H})/2'")
        v += f",{grade},fps={fps},setsar=1,format=yuv420p[v]"
    else:  # editorial frame: whole picture, never cropped, on a calm background
        inner = W - 120
        zoom = f"*(1+0.035*t/{dur:.3f})" if sh["type"] == "photo" else ""
        v = (f"color=c={bg}:s={W}x{H}:r={fps}:d={dur:.3f}[bg];"
             f"[0:v]scale=w='trunc({inner}{zoom}/2)*2':h=-2:eval=frame,{grade},setsar=1[fg];"
             f"[bg][fg]overlay=x='(W-w)/2':y='(H-h)/2-60':shortest=1:eval=frame,fps={fps},format=yuv420p[v]")

    if natural_audio and sh["type"] == "video" and sh.get("has_audio") and not sh.get("mute"):
        a = (f"[0:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.8,"
             f"apad,atrim=0:{dur:.3f},afade=t=in:d=0.3,afade=t=out:st={max(0, dur - 0.4):.3f}:d=0.4[a]")
    else:
        a = "[1:a]anull[a]"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", f"{v};{a}",
         "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
         "-c:a", "pcm_s16le", str(out)])
    return out


# ───────── subtitles ─────────
def ass_time(t: float) -> str:
    t = max(0.0, t)
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def write_subs(spec: dict, texts: list[dict], ass: Path, srt: Path, cfg: dict, cjk: bool) -> None:
    r = cfg["render"]
    f = r["font_cjk"] if cjk else r["font"]
    fb = r["font_cjk"] if cjk else r["font_brand"]
    white, shadow = "&H00FFFFFF", "&H99000000"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {r['width']}
PlayResY: {r['height']}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: hook,{f},64,{white},{white},&H00000000,{shadow},0,0,0,0,100,100,1,0,1,0,2,8,90,90,340,1
Style: line,{f},52,{white},{white},&H00000000,{shadow},0,0,0,0,100,100,1,0,1,0,2,2,100,100,560,1
Style: brand,{fb},84,{white},{white},&H00000000,{shadow},0,0,0,0,100,100,18,0,1,0,1,2,80,80,520,1
Style: story,{f},54,{white},{white},&H00000000,{shadow},0,0,0,0,100,100,1,0,1,0,2,2,100,100,430,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # shot active at time t → text colour (dark text on the light editorial frame)
    starts, t = [], 0.0
    for sh in spec["shots"]:
        starts.append((t, sh))
        t += sh["dur"] - cfg["render"]["transition"]

    def shot_at(tt: float) -> dict:
        cur = starts[0][1]
        for st, sh in starts:
            if st <= tt:
                cur = sh
        return cur

    ev, srt_lines = [], []
    for i, tx in enumerate(texts, 1):
        sh = shot_at(tx["start"] + 0.05)
        light_frame = sh["fit"] == "frame" and not is_dark(sh["lighting"])
        colour = r"{\c&H2A2A2A&\4a&HFF&}" if light_frame else ""
        body = tx["text"].replace("{", "(").replace("}", ")").replace(" m²", r"\hm²")
        if tx["style"] == "brand" and "\n" in body:
            head, _, rest = body.partition("\n")
            body = head + r"\N{\fs46\fsp2\fn" + (r["font_cjk"] if cjk else r["font"]) + "}" + rest.replace("\n", r"\N")
        body = body.replace("\n", r"\N")
        ev.append(f"Dialogue: 0,{ass_time(tx['start'])},{ass_time(tx['end'])},{tx['style']},,0,0,0,,"
                  rf"{{\fad(450,450)}}{colour}{body}")
        srt_lines.append(f"{i}\n{srt_time(tx['start'])} --> {srt_time(tx['end'])}\n{tx['text']}\n")
    ass.write_text(header + "\n".join(ev) + "\n", encoding="utf-8")
    srt.write_text("\n".join(srt_lines), encoding="utf-8")


# ───────── cover ─────────
def make_cover(first_clip: Path, t: float, title: str, out: Path, cfg: dict, cjk: bool = False) -> None:
    raw = out.with_suffix(".raw.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(first_clip),
         "-frames:v", "1", str(raw)])
    im = Image.open(raw).convert("RGB")
    raw.unlink()
    W, H = im.size
    d = ImageDraw.Draw(im, "RGBA")
    # soft vignette band in the 3:4 grid-safe centre so the title reads on any frame
    d.rectangle([0, int(H * 0.40), W, int(H * 0.60)], fill=(0, 0, 0, 60))
    f = font(cfg["render"]["font_cjk"] if cjk else "Inter Light", 62)
    fb = font("Inter ExtraLight", 40)
    lines = wrap(title, f, W - 180, d)
    y = H // 2 - (len(lines) * 76) // 2
    for ln in lines:
        w = d.textlength(ln, font=f)
        d.text(((W - w) / 2, y), ln, font=f, fill=(255, 255, 255, 240))
        y += 76
    brand = "M O N A D A"
    d.text(((W - d.textlength(brand, font=fb)) / 2, int(H * 0.62)), brand, font=fb, fill=(255, 255, 255, 220))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=92)


def wrap(text: str, f, maxw: int, d: ImageDraw.ImageDraw) -> list[str]:
    out = []
    for para in text.split("\n"):
        if " " not in para.strip():  # CJK or single word: wrap by characters
            line = ""
            for ch in para:
                if d.textlength(line + ch, font=f) > maxw and line:
                    out.append(line)
                    line = ch
                else:
                    line += ch
            out.append(line)
            continue
        line = ""
        for word in para.split():
            cand = (line + " " + word).strip()
            if d.textlength(cand, font=f) > maxw and line:
                out.append(line)
                line = word
            else:
                line = cand
        out.append(line)
    return out


# ───────── video spec ─────────
def localize(texts: list[dict], hook: str, lang: str) -> tuple[list[dict], str, list[str]]:
    table = (load_yaml("localization.yaml") or {}).get("strings", {})
    missing = []

    def tr(s: str) -> str:
        if not s:
            return s
        hit = table.get(s, {}).get(lang)
        if not hit:
            missing.append(s)
            return s
        return hit
    def tr_text(s: str) -> str:
        if s.startswith("MONADA"):
            head, _, rest = s.partition("\n")
            return head + ("\n" + tr(rest) if rest else "")
        return tr(s)
    return [{**t, "text": tr_text(t["text"])} for t in texts], tr(hook), missing


def render_video(spec: dict, archive: Path, cfg: dict, langs: list[str]) -> dict:
    r = cfg["render"]
    td = r["transition"] if len(spec["shots"]) > 1 else 0
    sub = {"reel": "reels", "story": "stories"}[spec["kind"]]
    odir = OUT / sub
    tdir = TMP / spec["out"]
    if tdir.exists():
        shutil.rmtree(tdir)
    tdir.mkdir(parents=True)
    natural = spec.get("audio", "natural") == "natural"
    clips = [shot_clip(sh, archive, tdir / f"{i:02d}.mov", cfg, natural) for i, sh in enumerate(spec["shots"])]

    # crossfade chain
    n = len(clips)
    ins = sum((["-i", str(c)] for c in clips), [])
    fc, vlast, alast, off = [], "[0:v]", "[0:a]", 0.0
    for i in range(1, n):
        off += spec["shots"][i - 1]["dur"] - td
        fc.append(f"{vlast}[{i}:v]xfade=transition=fade:duration={td}:offset={off:.3f}[v{i}]")
        fc.append(f"{alast}[{i}:a]acrossfade=d={td}:c1=tri:c2=tri[a{i}]")
        vlast, alast = f"[v{i}]", f"[a{i}]"
    music = spec.get("music")
    extra_in: list[str] = []
    if music:
        mp = LICENSED / music
        if not mp.exists() or not mp.with_suffix(mp.suffix + ".license.txt").exists():
            raise SystemExit(f"{spec['out']}: music '{music}' must be in music/licensed/ with a matching "
                             f"'{music}.license.txt' (proof of commercial licence).")
        extra_in = ["-stream_loop", "-1", "-i", str(mp)]
        fc.append(f"[{n}:a]atrim=0:{spec['duration']:.3f},afade=t=in:d=1,afade=t=out:st={spec['duration'] - 2:.3f}:d=2,volume=0.6[m]")
        fc.append(f"{alast}volume=0.35[nat];[nat][m]amix=inputs=2:normalize=0[amx]")
        alast = "[amx]"
    fc.append(f"{alast}loudnorm=I={r['loudness_lufs']}:TP=-1.5:LRA=11,aresample=48000[aout]")

    results = {}
    for lang in ["en"] + langs:
        texts, hook = spec["texts"], spec.get("hook", "")
        missing: list[str] = []
        if lang != "en":
            texts, hook, missing = localize(texts, hook, lang)
        suffix = "" if lang == "en" else f"_{lang}"
        name = spec["out"] + suffix
        ass, srt = tdir / f"subs{suffix}.ass", OUT / "subtitles" / f"{name}.srt"
        srt.parent.mkdir(parents=True, exist_ok=True)
        write_subs(spec, texts, ass, srt, cfg, cjk=lang in ("zh", "ko", "ja"))
        graph = ";".join(fc) + f";{vlast}subtitles=filename={ass.name}[vout]"
        odir.mkdir(parents=True, exist_ok=True)
        mp4 = odir / f"{name}.mp4"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *ins, *extra_in, "-filter_complex", graph,
             "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "slow", "-crf", str(r["crf"]),
             "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-r", str(r["fps"]),
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(mp4.resolve())],
            cwd=tdir)
        if spec["kind"] == "reel":
            make_cover(clips[0], min(1.2, spec["shots"][0]["dur"] / 2), hook or spec["title"],
                       OUT / "covers" / f"{name}.jpg", cfg, cjk=lang in ("zh", "ko"))
        results[lang] = qa(spec, mp4, cfg, missing)
        (odir / f"{name}.qa.json").write_text(json.dumps(results[lang], indent=2, ensure_ascii=False))
    shutil.rmtree(tdir, ignore_errors=True)
    return results


def qa(spec: dict, mp4: Path, cfg: dict, missing_tr: list[str]) -> dict:
    r = cfg["render"]
    info = ffprobe(mp4)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    dur = float(info["format"]["duration"])
    warn = []
    if (v["width"], v["height"]) != (r["width"], r["height"]):
        warn.append(f"resolution {v['width']}x{v['height']}")
    if v["codec_name"] != "h264":
        warn.append(f"codec {v['codec_name']}")
    if spec["kind"] == "reel":
        lo, hi = 15, (45 if spec.get("reveal") else 30)
        if not lo - 0.5 <= dur <= hi + 0.5:
            warn.append(f"duration {dur:.1f}s outside {lo}–{hi}s")
        if not spec["texts"] or spec["texts"][0]["start"] > 0.5:
            warn.append("hook text not on screen in first 2 s")
        if spec["shots"][0]["dur"] < 2.0:
            warn.append("hook shot shorter than 2 s")
    for sh in spec["shots"]:
        if sh["upscale"] > r["max_upscale"] and sh["fit"] == "cover":
            warn.append(f"{sh['shot_id']}: upscaled ×{sh['upscale']} (may look soft)")
        if sh["fit"] == "frame":
            warn.append(f"{sh['shot_id']}: horizontal source shown framed (crop would keep {int(sh['crop_retention'] * 100)}%)")
        if sh.get("mute"):
            warn.append(f"{sh['shot_id']}: source audio muted (music/voices flagged or unchecked)")
        if str(sh.get("may_be_outdated", "?")) in ("?", "y", "yes"):
            warn.append(f"{sh['shot_id']}: owner to confirm still current ({sh.get('captured_at')})")
    if missing_tr:
        warn.append(f"untranslated lines left in English: {missing_tr}")
    return {"file": str(mp4.relative_to(ROOT)), "duration": round(dur, 2), "width": v["width"], "height": v["height"],
            "codec": v["codec_name"], "pix_fmt": v.get("pix_fmt"), "fps": v.get("avg_frame_rate"),
            "sources": [{k: sh[k] for k in ("shot_id", "file", "t_in", "dur", "fit", "captured_at", "archival")}
                        for sh in spec["shots"]],
            "fact_issues": spec.get("fact_issues", []), "warnings": warn, "owner_approved": False}


# ───────── carousel ─────────
def render_carousel(spec: dict, archive: Path, cfg: dict) -> list[Path]:
    W, H = 1080, 1350
    odir = OUT / "carousels" / spec["out"]
    odir.mkdir(parents=True, exist_ok=True)
    outs = []
    sand, ink = cfg["render"]["frame_bg_light"], "#2A2A2A"
    for i, sl in enumerate(spec["slides"], 1):
        src = archive / sl["file"]
        if sl["type"] == "video":
            tmp = odir / f"_frame{i}.png"
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{sl['t']:.2f}", "-i", str(src),
                 "-frames:v", "1", str(tmp)])
            im = Image.open(tmp).convert("RGB")
            tmp.unlink()
        else:
            im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
        s = max(W / im.width, H / im.height)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        x = int((im.width - W) * min(max(sl.get("focus_x", 0.5), 0), 1))
        im = im.crop((x, (im.height - H) // 2, x + W, (im.height - H) // 2 + H))
        im = Image.eval(im, lambda p: int(p * 0.98))  # tiny highlight roll-off for an editorial feel
        if i == 1:
            d = ImageDraw.Draw(im, "RGBA")
            d.rectangle([0, H - 300, W, H], fill=(0, 0, 0, 70))
            f = font("Inter-Light.otf", 50)
            y = H - 230
            for ln in wrap(spec["title"], f, W - 160, d):
                d.text((80, y), ln, font=f, fill=(255, 255, 255, 240))
                y += 64
            d.text((80, H - 80), "M O N A D A", font=font("Inter-ExtraLight.otf", 28), fill=(255, 255, 255, 220))
        p = odir / f"{i:02d}.jpg"
        im.save(p, quality=93)
        outs.append(p)
    if spec.get("end_text"):
        im = Image.new("RGB", (W, H), sand)
        d = ImageDraw.Draw(im)
        f = font("Inter-Light.otf", 58)
        lines = spec["end_text"].split("\n")
        y = H // 2 - len(lines) * 40
        for ln in lines:
            d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=ink)
            y += 80
        p = odir / f"{len(outs) + 1:02d}.jpg"
        im.save(p, quality=93)
        outs.append(p)
    (odir / "caption.txt").write_text(spec["caption"] + "\n\n" + " ".join(spec["hashtags"]) + "\n", encoding="utf-8")
    return outs


def render_all(archive: Path, only: list[str] | None, langs: list[str], skip_b: bool = False) -> None:
    cfg = settings()
    specs = sorted(SPECS.glob("*.json"))
    if not specs:
        raise SystemExit("No specs — run `python -m monada compose` first.")
    for p in specs:
        spec = json.loads(p.read_text())
        if only and not any(o in p.stem for o in only):
            continue
        if skip_b and spec.get("variant") == "B":
            continue
        if spec["kind"] == "carousel":
            if spec["slides"]:
                outs = render_carousel(spec, archive, cfg)
                print(f"✓ {p.stem}: {len(outs)} slides")
            continue
        res = render_video(spec, archive, cfg, langs if spec["kind"] == "reel" else [])
        w = res["en"]["warnings"]
        print(f"✓ {p.stem}: {res['en']['duration']}s" + (f"  ⚠ {len(w)} warning(s)" if w else ""))
