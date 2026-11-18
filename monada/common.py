"""Shared paths, config loading and ffmpeg/ffprobe helpers."""
from __future__ import annotations

import csv
import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN = ROOT / "campaign"
LIBRARY = ROOT / "library"
BUILD = ROOT / "build"
OUT = ROOT / "out"

SHOT_INDEX = LIBRARY / "shot_index.csv"
TAGS = LIBRARY / "tags.csv"

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif", ".dng"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mts", ".m2ts", ".3gp", ".webm"}

TAG_FIELDS = [
    "shot_id", "file", "subject", "lighting", "shot_type", "mood", "crop_focus_x",
    "people_present", "music_in_source", "may_be_outdated", "use", "notes",
]


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CAMPAIGN / name).read_text(encoding="utf-8"))


def settings() -> dict:
    return load_yaml("settings.yaml")


def facts() -> dict:
    return load_yaml("facts.yaml")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(map(str, cmd))[:400]}\n{p.stderr[-2000:]}")
    return p


def ffprobe(path: Path) -> dict:
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(p.stdout)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def split_tags(v: str | None) -> set[str]:
    return {t.strip().lower() for t in re.split(r"[;,|\s]+", v or "") if t.strip()}


FACT_RE = re.compile(r"\{\{(\w+)\}\}")


def resolve_facts(text: str, fact_table: dict | None = None) -> tuple[str, list[str]]:
    """Replace {{fact}} placeholders. Returns (text, list of unverified/missing fact names)."""
    fact_table = fact_table or facts()
    problems: list[str] = []

    def sub(m):
        k = m.group(1)
        f = fact_table.get(k)
        if not f or f.get("value") in (None, ""):
            problems.append(f"{k}:missing")
            return f"[{k.upper()}?]"
        if not f.get("verified"):
            problems.append(f"{k}:unverified")
        return str(f["value"])

    return FACT_RE.sub(sub, text or ""), problems


def load_shots() -> list[dict]:
    """shot_index.csv merged with human/AI tags from tags.csv (tags win)."""
    shots = read_csv(SHOT_INDEX)
    tags = {r["shot_id"]: r for r in read_csv(TAGS)}
    asset_tags = {r["shot_id"]: r for r in read_csv(TAGS) if "_s" not in r["shot_id"]}
    for s in shots:
        t = tags.get(s["shot_id"]) or asset_tags.get(s["asset_id"]) or {}
        for k in TAG_FIELDS[2:]:
            if t.get(k):
                s[k] = t[k]
            else:
                s.setdefault(k, "")
        if not s.get("lighting"):
            s["lighting"] = s.get("lighting_auto", "")
        for k in ("width", "height", "duration", "t_in", "t_out", "quality", "crop_retention", "upscale", "age_months"):
            try:
                s[k] = float(s.get(k) or 0)
            except ValueError:
                s[k] = 0.0
    return shots
