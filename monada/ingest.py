"""Steps 1–4: ingest archive, detect scenes, rate quality, de-duplicate, build the shot index + contact sheets."""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .common import (LIBRARY, PHOTO_EXT, SHOT_INDEX, TAG_FIELDS, TAGS, VIDEO_EXT, ffprobe, read_csv,
                     run, settings, write_csv)

THUMBS = LIBRARY / "thumbs"
SHEETS = LIBRARY / "contact_sheets"

INDEX_FIELDS = [
    "shot_id", "asset_id", "file", "type", "t_in", "t_out", "duration", "width", "height", "orientation",
    "aspect", "fps", "has_audio", "captured_at", "date_source", "age_months", "archival", "sharpness",
    "brightness", "saturation", "warmth", "lighting_auto", "crop_retention", "upscale", "quality", "grade",
    "dup_of", "dhash", "thumb", "issues",
]

try:  # optional HEIC support
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
    HEIC_OK = True
except Exception:  # pragma: no cover
    HEIC_OK = False


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ───────── metadata ─────────
def photo_meta(path: Path) -> dict:
    im = Image.open(path)
    date = None
    try:
        ex = im.getexif()
        raw = ex.get_ifd(0x8769).get(36867) or ex.get(306)
        if raw:
            date = dt.datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    im = ImageOps.exif_transpose(im)
    return {"width": im.width, "height": im.height, "duration": 0.0, "fps": "", "has_audio": "n",
            "captured_at": date, "date_source": "exif" if date else ""}


def video_meta(path: Path) -> dict:
    info = ffprobe(path)
    v = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    if not v:
        raise ValueError("no video stream")
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    rot = rot or int(v.get("tags", {}).get("rotate", 0) or 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = round(float(num) / float(den or 1), 2) if float(den or 1) else 0
    dur = float(info["format"].get("duration") or v.get("duration") or 0)
    ct = info["format"].get("tags", {}).get("creation_time") or v.get("tags", {}).get("creation_time")
    date = None
    if ct:
        try:
            date = dt.datetime.fromisoformat(ct.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    has_audio = any(s.get("codec_type") == "audio" for s in info["streams"])
    return {"width": w, "height": h, "duration": dur, "fps": fps, "has_audio": "y" if has_audio else "n",
            "captured_at": date, "date_source": "container" if date else ""}


def scene_cuts(path: Path, duration: float, threshold: float = 0.32, min_len: float = 1.5) -> list[tuple[float, float]]:
    if duration <= 8:
        return [(0.0, duration)]
    p = run(["ffmpeg", "-hide_banner", "-i", str(path), "-an", "-vf",
             f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"])
    cuts = [float(m) for m in re.findall(r"pts_time:([\d.]+)", p.stderr)]
    bounds = [0.0] + [c for c in cuts if 0 < c < duration] + [duration]
    segs: list[list[float]] = []
    for a, b in zip(bounds, bounds[1:]):
        if segs and (b - a) < min_len:
            segs[-1][1] = b
        else:
            segs.append([a, b])
    if len(segs) > 1 and segs[0][1] - segs[0][0] < min_len:
        segs[1][0] = segs[0][0]
        segs.pop(0)
    # long uncut takes (handheld walkthroughs): chunk so each piece can be tagged by room
    out: list[list[float]] = []
    for a, b in segs:
        if b - a > 20:
            n = max(2, round((b - a) / 6))
            step = (b - a) / n
            out += [[a + i * step, a + (i + 1) * step] for i in range(n)]
        else:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


# ───────── image metrics ─────────
def frame_from_video(path: Path, t: float, out: Path) -> Image.Image:
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3", str(out)])
    return Image.open(out).convert("RGB")


def frame_from_photo(path: Path, out: Path) -> Image.Image:
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((640, 640))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=88)
    return im


def metrics(im: Image.Image) -> dict:
    a = np.asarray(im, dtype=np.float32)
    g = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    small = np.asarray(im.convert("L").resize((9, 8), Image.BILINEAR), dtype=np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    dh = int("".join("1" if b else "0" for b in bits), 2)
    return {
        "sharpness": float(lap.var()),
        "brightness": float(g.mean()),
        "clipped": float(((g > 250) | (g < 5)).mean()),
        "saturation": float(sat.mean()),
        "warmth": float(a[..., 0].mean() - a[..., 2].mean()),
        "dhash": dh,
    }


def lighting_guess(m: dict) -> str:
    b, w = m["brightness"], m["warmth"]
    if b < 55:
        return "night"
    if b < 95 and w > 12:
        return "evening"
    if w > 22 and b < 170:
        return "golden"
    if m["saturation"] < 0.12 and b < 150:
        return "overcast"
    return "day"


def crop_stats(w: int, h: int, W: int, H: int) -> tuple[float, float]:
    s = max(W / w, H / h)
    retention = (W / s) * (H / s) / (w * h)
    return round(retention, 3), round(s, 3)


def quality(m: dict, upscale: float) -> float:
    res = 100.0 if upscale <= 1 else max(0.0, 100 - (upscale - 1) * 80)
    sharp = min(100.0, max(0.0, (math.log10(m["sharpness"] + 1) - 1.5) / (2.6 - 1.5) * 100))
    b = m["brightness"]
    expo = 100 - max(0, 60 - b) * 1.2 - max(0, b - 200) * 1.5 - m["clipped"] * 150
    return round(0.30 * res + 0.50 * sharp + 0.20 * max(0, expo), 1)


def grade(q: float) -> str:
    return "A" if q >= 75 else "B" if q >= 55 else "C" if q >= 35 else "reject"


# ───────── contact sheets ─────────
def contact_sheets(rows: list[dict], per_sheet: int = 20, cols: int = 4, cell: int = 320) -> list[Path]:
    SHEETS.mkdir(parents=True, exist_ok=True)
    for old in SHEETS.glob("sheet_*.jpg"):
        old.unlink()
    try:
        font = ImageFont.truetype("Inter-Regular.otf", 15)
    except OSError:
        font = ImageFont.load_default()
    out = []
    live = [r for r in rows if not r["dup_of"]]
    for i in range(0, len(live), per_sheet):
        chunk = live[i:i + per_sheet]
        nrows = math.ceil(len(chunk) / cols)
        sheet = Image.new("RGB", (cols * cell, nrows * (cell + 40)), "#f2efe9")
        d = ImageDraw.Draw(sheet)
        for j, r in enumerate(chunk):
            x, y = (j % cols) * cell, (j // cols) * (cell + 40)
            im = Image.open(LIBRARY / r["thumb"]).convert("RGB")
            im.thumbnail((cell - 10, cell - 10))
            sheet.paste(im, (x + (cell - im.width) // 2, y + 5 + (cell - 10 - im.height) // 2))
            label = f"{r['shot_id']}  {r['type'][0].upper()} {r['orientation']}  {r['grade']}  {r['lighting_auto']}"
            d.text((x + 6, y + cell + 2), label, fill="#222", font=font)
            d.text((x + 6, y + cell + 20), Path(r["file"]).name[:38], fill="#666", font=font)
        p = SHEETS / f"sheet_{i // per_sheet + 1:03d}.jpg"
        sheet.save(p, quality=85)
        out.append(p)
    return out


# ───────── main ─────────
def ingest(archive: Path) -> list[dict]:
    cfg = settings()
    W, H = cfg["render"]["width"], cfg["render"]["height"]
    archival_after = cfg["library"]["archival_after_months"]
    today = dt.datetime.now()
    files = sorted(p for p in archive.rglob("*") if p.is_file() and p.suffix.lower() in PHOTO_EXT | VIDEO_EXT
                   and not p.name.startswith("."))
    rows: list[dict] = []
    seen_sha: dict[str, str] = {}
    for f in files:
        rel = str(f.relative_to(archive))
        is_video = f.suffix.lower() in VIDEO_EXT
        digest = sha1(f)
        asset_id = digest[:12]
        base = {"asset_id": asset_id, "file": rel, "type": "video" if is_video else "photo", "issues": ""}
        if digest in seen_sha:
            rows.append({**base, "shot_id": asset_id + "_dup", "dup_of": seen_sha[digest], "grade": "reject",
                         "issues": "exact duplicate file"})
            continue
        try:
            if f.suffix.lower() in {".heic", ".heif"} and not HEIC_OK:
                raise ValueError("HEIC not readable here — export as JPG or `pip install pillow-heif`")
            meta = video_meta(f) if is_video else photo_meta(f)
        except Exception as e:  # unreadable file — keep a row so nothing silently disappears
            rows.append({**base, "shot_id": asset_id, "grade": "reject", "dup_of": "", "issues": f"unreadable: {e}"})
            continue
        if not meta["captured_at"]:
            meta["captured_at"] = dt.datetime.fromtimestamp(f.stat().st_mtime)
            meta["date_source"] = "file-mtime (unreliable)"
        age = (today - meta["captured_at"]).days / 30.44
        w, h = meta["width"], meta["height"]
        retention, upscale = crop_stats(w, h, W, H)
        segs = scene_cuts(f, meta["duration"]) if is_video else [(0.0, 0.0)]
        first_shot_id = None
        for k, (a, b) in enumerate(segs):
            shot_id = f"{asset_id}_s{k + 1:02d}" if is_video and len(segs) > 1 else asset_id
            first_shot_id = first_shot_id or shot_id
            thumb = Path("thumbs") / f"{shot_id}.jpg"
            if is_video:
                ms = [metrics(frame_from_video(f, a + (b - a) * q, THUMBS / f"{shot_id}{'' if q == 0.5 else '_q'}.jpg"))
                      for q in (0.25, 0.5)]
                m = {k2: (sum(x[k2] for x in ms) / 2 if k2 != "dhash" else ms[1][k2]) for k2 in ms[0]}
                (THUMBS / f"{shot_id}_q.jpg").unlink(missing_ok=True)
            else:
                m = metrics(frame_from_photo(f, LIBRARY / thumb))
            q = quality(m, upscale)
            issues = []
            cropped = retention >= cfg["render"]["min_crop_retention"] or h > w
            if cropped and upscale > cfg["render"]["max_upscale"]:
                issues.append(f"low-res for 9:16 (upscale ×{upscale})")
            if not cropped:
                issues.append(f"9:16 crop would keep {int(retention * 100)}% — will be shown framed")
            if is_video and (b - a) < 2:
                issues.append("short shot")
            rows.append({
                **base, "shot_id": shot_id, "t_in": a, "t_out": b, "duration": round(b - a, 3) if is_video else 0,
                "width": w, "height": h,
                "orientation": "vertical" if h > w * 1.05 else "horizontal" if w > h * 1.05 else "square",
                "aspect": f"{w / h:.3f}", "fps": meta["fps"], "has_audio": meta["has_audio"],
                "captured_at": meta["captured_at"].strftime("%Y-%m-%d"), "date_source": meta["date_source"],
                "age_months": round(age, 1), "archival": "y" if age > archival_after else "n",
                "sharpness": round(m["sharpness"], 1), "brightness": round(m["brightness"], 1),
                "saturation": round(m["saturation"], 3), "warmth": round(m["warmth"], 1),
                "lighting_auto": lighting_guess(m), "crop_retention": retention, "upscale": upscale,
                "quality": q, "grade": grade(q), "dup_of": "", "dhash": f"{m['dhash']:016x}", "thumb": str(thumb),
                "issues": "; ".join(issues),
            })
        seen_sha[digest] = first_shot_id

    # near-duplicates (different files, same picture): keep the best-rated one
    thr = cfg["library"]["near_dup_hamming"]
    live = sorted([r for r in rows if r.get("dhash") and not r["dup_of"]], key=lambda r: -float(r["quality"]))
    kept: list[dict] = []
    for r in live:
        h1 = int(r["dhash"], 16)
        twin = next((k for k in kept if k["asset_id"] != r["asset_id"] and k["type"] == r["type"]
                     and bin(h1 ^ int(k["dhash"], 16)).count("1") <= thr
                     and abs(float(k["brightness"]) - float(r["brightness"])) < 12
                     and abs(float(k["warmth"]) - float(r["warmth"])) < 10
                     and abs(float(k["saturation"]) - float(r["saturation"])) < 0.06), None)
        if twin:
            r["dup_of"] = twin["shot_id"]
            r["issues"] = (r["issues"] + "; " if r["issues"] else "") + "near-duplicate"
        else:
            kept.append(r)

    write_csv(SHOT_INDEX, rows, INDEX_FIELDS)

    # tags.csv: add rows for new shots, never overwrite human/AI tags
    existing = {r["shot_id"]: r for r in read_csv(TAGS)}
    for r in rows:
        if r["shot_id"] not in existing and not r.get("dup_of") and r["grade"] != "reject":
            existing[r["shot_id"]] = {"shot_id": r["shot_id"], "file": r["file"], "may_be_outdated": "?",
                                      "use": "y", "crop_focus_x": "0.5"}
    write_csv(TAGS, sorted(existing.values(), key=lambda r: r["file"] + r["shot_id"]), TAG_FIELDS)
    sheets = contact_sheets([r for r in rows if r.get("thumb")])

    ok = [r for r in rows if not r.get("dup_of") and r["grade"] != "reject"]
    print(f"files: {len(files)}  shots: {len(rows)}  usable: {len(ok)}  "
          f"duplicates: {sum(1 for r in rows if r.get('dup_of'))}  rejected: {sum(1 for r in rows if r['grade'] == 'reject')}")
    print(f"grades: " + ", ".join(f"{g}={sum(1 for r in ok if r['grade'] == g)}" for g in "ABC"))
    print(f"wrote {SHOT_INDEX.relative_to(SHOT_INDEX.parents[1])}, {TAGS.name}, {len(sheets)} contact sheet(s)")
    return rows
