"""Step 5: fill reel / story / carousel templates with real shots from the index → build/specs/*.json."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .common import BUILD, ROOT, load_shots, load_yaml, resolve_facts, settings, split_tags

SPECS = BUILD / "specs"
MIN_LEN, TARGET_LEN, MAX_LEN = 15.0, 17.0, 30.0


class Picker:
    def __init__(self, shots: list[dict], cfg: dict):
        self.cfg = cfg
        self.max_uses = cfg["library"]["max_uses_per_shot"]
        self.min_ret = cfg["render"]["min_crop_retention"]
        self.shots = [s for s in shots if self.usable(s)]
        self.uses: Counter = Counter()
        self.hook_used: set[str] = set()

    @staticmethod
    def usable(s: dict) -> bool:
        return (not s.get("dup_of") and s.get("grade") not in ("reject", "")
                and s.get("use", "y").lower() not in ("n", "no", "0")
                and s.get("people_present", "").lower() not in ("y", "yes", "guest", "guests"))

    def candidates(self, need: dict, exclude: set[str], role: str = "", best: bool = False) -> list[tuple[float, dict]]:
        subj, light = set(need.get("subject") or []), set(need.get("lighting") or [])
        stype, prefer = set(need.get("shot_type") or []), need.get("prefer")
        out = []
        for s in self.shots:
            if s["shot_id"] in exclude:
                continue
            if subj and not (split_tags(s["subject"]) & subj):
                continue
            if light and not (split_tags(s["lighting"]) & light):
                continue
            if not best and self.uses[s["shot_id"]] >= self.max_uses:
                continue
            if s["type"] == "video" and s["duration"] < 1.5:
                continue
            sc = s["quality"]
            if prefer and s["type"] == prefer:
                sc += 12
            if stype and split_tags(s["shot_type"]) & stype:
                sc += 8
            if s["orientation"] == "vertical" or s["crop_retention"] >= self.min_ret:
                sc += 6
            if s["type"] == "video" and need.get("dur") and s["duration"] < need["dur"]:
                sc -= 15
            if not best:
                sc -= 30 * self.uses[s["shot_id"]]
            if role == "hook" and s["shot_id"] in self.hook_used:
                sc -= 60
            out.append((sc, s))
        return sorted(out, key=lambda x: -x[0])

    def take(self, s: dict, hook: bool = False) -> None:
        self.uses[s["shot_id"]] += 1
        if hook:
            self.hook_used.add(s["shot_id"])


def fit_mode(s: dict, min_ret: float) -> str:
    return "cover" if (s["orientation"] == "vertical" or s["crop_retention"] >= min_ret) else "frame"


def shot_entry(s: dict, slot: dict, dur: float, use_n: int, idx: int, min_ret: float) -> dict:
    t_in = 0.0
    if s["type"] == "video":
        seg = s["t_out"] - s["t_in"]
        dur = min(dur, seg)
        frac = (0.5, 0.15, 0.85, 0.35)[use_n % 4]
        t_in = s["t_in"] + max(0.0, seg - dur) * frac
    try:
        fx = float(s.get("crop_focus_x") or 0.5)
    except ValueError:
        fx = 0.5
    return {
        "shot_id": s["shot_id"], "file": s["file"], "type": s["type"], "t_in": round(t_in, 3),
        "dur": round(dur, 3), "fit": fit_mode(s, min_ret), "focus_x": fx,
        "motion": ("pan_right" if idx % 2 == 0 else "pan_left") if s["type"] == "photo" else "none",
        "role": slot.get("role", ""), "text": slot.get("text", ""), "lighting": s["lighting"],
        "has_audio": s.get("has_audio") == "y", "mute": s.get("music_in_source", "").lower() in ("y", "yes", "?"),
        "archival": s.get("archival") == "y", "captured_at": s.get("captured_at", ""),
        "may_be_outdated": s.get("may_be_outdated", "?"), "crop_retention": s["crop_retention"],
        "upscale": s["upscale"], "grade": s["grade"],
    }


def scale_slots(slots: list[dict], td: float, max_len: float) -> list[float]:
    durs = [float(sl.get("dur", 3)) for sl in slots]
    total = sum(durs) - (len(durs) - 1) * td
    if total < MIN_LEN:
        f = (TARGET_LEN + (len(durs) - 1) * td) / sum(durs)
        durs = [d * f for d in durs]
    elif total > max_len:
        f = (max_len - 0.5 + (len(durs) - 1) * td) / sum(durs)
        durs = [d * f for d in durs]
    return [round(d, 2) for d in durs]


def fill(picker: Picker, story: dict, td: float, max_len: float) -> tuple[list[dict] | None, list[str], dict | None]:
    """Returns (shots for variant A, gap messages, alt hook shot)."""
    durs = scale_slots(story["slots"], td, max_len)
    chosen, gaps, used = [], [], set()
    alt = None
    for i, (slot, d) in enumerate(zip(story["slots"], durs)):
        need = {**slot, "dur": d}
        cands = picker.candidates(need, used, slot.get("role", ""), best=bool(slot.get("best") or story.get("reveal")))
        if not cands:
            gaps.append(f"slot {i + 1} ({slot.get('role') or 'shot'}): no shot with subject={slot.get('subject')}"
                        + (f" lighting={slot.get('lighting')}" if slot.get("lighting") else ""))
            continue
        s = cands[0][1]
        chosen.append((slot, d, s))
        used.add(s["shot_id"])
        if slot.get("role") == "hook":
            alt = next((c[1] for c in cands[1:] if c[1]["shot_id"] != s["shot_id"]), None)
    return chosen, gaps, alt


def timeline(shots: list[dict], td: float, hook: str) -> tuple[list[dict], float]:
    texts, t = [], 0.0
    for i, sh in enumerate(shots):
        start = t
        end = t + sh["dur"]
        if i == 0 and hook:
            texts.append({"start": 0.15, "end": min(end - td * 0.5, 3.2), "text": hook, "style": "hook"})
        if sh["text"]:
            style = "brand" if sh["role"] == "endcard" else "line"
            texts.append({"start": round(start + (td if i else 0) + 0.2, 2), "end": round(end - 0.15, 2),
                          "text": sh["text"], "style": style})
        t = end - td
    total = round(sum(s["dur"] for s in shots) - (len(shots) - 1) * td, 2)
    return texts, total


def compose_all() -> dict:
    cfg = settings()
    td = cfg["render"]["transition"]
    min_ret = cfg["render"]["min_crop_retention"]
    reels = sorted(load_yaml("reels.yaml")["reels"], key=lambda r: r["day"])
    shots = load_shots()
    if not shots:
        raise SystemExit("library/shot_index.csv is empty — run `python -m monada ingest` first.")
    picker = Picker(shots, cfg)
    SPECS.mkdir(parents=True, exist_ok=True)
    for old in SPECS.glob("*.json"):
        old.unlink()
    report = {"reels": [], "stories": [], "carousels": []}
    reel_specs: dict[str, dict] = {}

    for r in reels:
        max_len = float(r.get("duration_max", MAX_LEN))
        story, used_fallback = r, False
        chosen, gaps, alt = fill(picker, r, td, max_len)
        if gaps and r.get("fallback"):
            # undo nothing (fill doesn't commit usage); try the fallback story
            fb = {**r, **r["fallback"]}
            c2, g2, a2 = fill(picker, fb, td, max_len)
            if len(g2) < len(gaps):
                story, chosen, gaps, alt, used_fallback = fb, c2, g2, a2, True
        hook_ok = chosen and chosen[0][0].get("role") == "hook"
        status = "ok" if not gaps else ("partial" if hook_ok and len(chosen) >= max(3, 0.6 * len(story["slots"])) else "gap")
        entry = {"id": r["id"], "day": r["day"], "title": story["title"], "status": status,
                 "fallback": used_fallback, "gaps": gaps}
        report["reels"].append(entry)
        if status == "gap":
            continue
        # partial reels: stretch the shots we do have back to >= MIN_LEN (within each clip's real length)
        total = sum(d for _, d, _ in chosen) - (len(chosen) - 1) * td
        if total < MIN_LEN:
            f = (TARGET_LEN + (len(chosen) - 1) * td) / sum(d for _, d, _ in chosen)
            chosen = [(sl, min(round(d * f, 2), 6.0) if s["type"] == "photo" else min(round(d * f, 2), s["duration"]), s)
                      for sl, d, s in chosen]
        shots_a = []
        for i, (slot, d, s) in enumerate(chosen):
            shots_a.append(shot_entry(s, slot, d, picker.uses[s["shot_id"]], i, min_ret))
            picker.take(s, hook=slot.get("role") == "hook")
        hook_a, _ = resolve_facts(story["hook"])
        hook_b, _ = resolve_facts(story.get("alt_hook", ""))
        caption, fact_issues = resolve_facts(r["caption"])
        for sh in shots_a:
            sh["text"], fi = resolve_facts(sh["text"])
            fact_issues += fi
        _, fi = resolve_facts(story["hook"] + " " + story.get("alt_hook", ""))
        fact_issues = sorted(set(fact_issues + fi))
        hashtags = cfg["hashtags_base"] + r.get("hashtags", [])
        base = {"id": r["id"], "day": r["day"], "title": story["title"], "reveal": bool(r.get("reveal")),
                "markets": r.get("markets", []), "audio": r.get("audio", "natural"), "music": r.get("music"),
                "caption": caption.strip(), "hashtags": hashtags, "fact_issues": fact_issues,
                "notes": r.get("notes", ""), "status": status, "gaps": gaps, "fallback": used_fallback}
        variants = {"A": (hook_a, shots_a)}
        if alt and hook_b:
            shots_b = [dict(sh) for sh in shots_a]
            shots_b[0] = shot_entry(alt, chosen[0][0], chosen[0][1], picker.uses[alt["shot_id"]], 0, min_ret)
            picker.take(alt, hook=True)
            variants["B"] = (hook_b, shots_b)
        for v, (hook, shots_v) in variants.items():
            texts, total = timeline(shots_v, td, hook)
            spec = {**base, "variant": v, "hook": hook, "shots": shots_v, "texts": texts, "duration": total,
                    "kind": "reel", "out": f"D{r['day']:02d}_{r['id']}_{v}"}
            (SPECS / f"{spec['out']}.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False))
            if v == "A":
                reel_specs[r["id"]] = spec
        entry.update({"duration": reel_specs[r["id"]]["duration"], "variants": list(variants),
                      "archival_shots": sum(1 for s in shots_a if s["archival"]),
                      "framed_shots": sum(1 for s in shots_a if s["fit"] == "frame"),
                      "soft_shots": sum(1 for s in shots_a if s["upscale"] > cfg["render"]["max_upscale"]),
                      "fact_issues": fact_issues})

    # Stories
    for st in load_yaml("stories.yaml")["stories"]:
        for k, fr in enumerate(st["frames"], 1):
            s = None
            if fr.get("from") and fr["from"] in reel_specs:
                src = reel_specs[fr["from"]]["shots"]
                sid = src[min(k, len(src) - 1)]["shot_id"] if k > 1 else src[0]["shot_id"]
                s = next((x for x in picker.shots if x["shot_id"] == sid), None)
            if s is None:
                need = {"subject": fr.get("subject"), "lighting": fr.get("lighting"), "dur": 6}
                c = picker.candidates(need, set())
                s = c[0][1] if c else None
            sid = f"D{st['day']:02d}_S{k}"
            if s is None:
                report["stories"].append({"id": sid, "status": "gap", "need": fr})
                continue
            sh = shot_entry(s, {"role": "story", "text": ""}, 6.0, picker.uses[s["shot_id"]], k, cfg["render"]["min_crop_retention"])
            picker.uses[s["shot_id"]] += 0  # stories reuse freely; don't consume reel budget
            text, fi = resolve_facts(fr.get("text", ""))
            spec = {"id": sid, "day": st["day"], "kind": "story", "variant": "", "reveal": bool(st.get("reveal")),
                    "audio": "natural", "music": None, "shots": [sh], "hook": "",
                    "texts": [{"start": 0.3, "end": sh["dur"] - 0.3, "text": text, "style": "story"}] if text else [],
                    "duration": sh["dur"], "sticker": fr.get("sticker", ""), "fact_issues": fi, "out": sid,
                    "caption": "", "hashtags": [], "status": "ok"}
            (SPECS / f"{sid}.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False))
            report["stories"].append({"id": sid, "status": "ok", "shot": s["shot_id"], "sticker": fr.get("sticker", "")})

    # Carousels (prefer photos; 4:5)
    for c in load_yaml("carousels.yaml")["carousels"]:
        used, slides, gaps = set(), [], []
        for i, need in enumerate(c["need"]):
            cands = picker.candidates({**need, "prefer": "photo"}, used)
            if not cands:
                gaps.append(f"slide {i + 1}: subject={need.get('subject')}")
                continue
            s = cands[0][1]
            used.add(s["shot_id"])
            picker.take(s)
            slides.append({"shot_id": s["shot_id"], "file": s["file"], "type": s["type"],
                           "t": round((s["t_in"] + s["t_out"]) / 2, 3) if s["type"] == "video" else 0,
                           "focus_x": float(s.get("crop_focus_x") or 0.5), "archival": s.get("archival") == "y"})
        caption, fi = resolve_facts(c["caption"])
        spec = {"id": c["id"], "day": c["day"], "kind": "carousel", "title": c["title"], "slides": slides,
                "end_text": c.get("end_text", ""), "caption": caption.strip(),
                "hashtags": cfg["hashtags_base"] + c.get("hashtags", []), "fact_issues": fi, "gaps": gaps,
                "status": "ok" if not gaps else ("partial" if len(slides) >= 3 else "gap"),
                "out": f"D{c['day']:02d}_{c['id']}"}
        (SPECS / f"{spec['out']}.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False))
        report["carousels"].append({"id": c["id"], "day": c["day"], "status": spec["status"], "gaps": gaps})

    write_report(report, picker)
    (BUILD / "compose_status.json").write_text(json.dumps(
        {**{e["id"]: e["status"] for e in report["reels"]}, **{c["id"]: c["status"] for c in report["carousels"]}}))
    return report


def write_report(report: dict, picker: Picker) -> None:
    lines = ["# Compose report", "", "Generated by `python -m monada compose`. Gaps mean the archive has no suitable "
             "real footage — tag more shots or accept the fallback; never fill with generated imagery.", "",
             "## Reels", "", "| Day | ID | Title | Status | Len (s) | Variants | Archival | Framed | Soft | Unverified facts | Gaps |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in report["reels"]:
        lines.append(f"| {e['day']} | {e['id']} | {e['title']}{' (fallback)' if e['fallback'] else ''} | {e['status']} | "
                     f"{e.get('duration', '')} | {'/'.join(e.get('variants', []))} | {e.get('archival_shots', '')} | "
                     f"{e.get('framed_shots', '')} | {e.get('soft_shots', '')} | {', '.join(e.get('fact_issues', []))} | "
                     f"{'<br>'.join(e['gaps'])} |")
    lines += ["", "## Carousels", ""] + [f"- D{c['day']:02d} {c['id']}: **{c['status']}** {'; '.join(c['gaps'])}"
                                          for c in report["carousels"]]
    sg = [s for s in report["stories"] if s["status"] == "gap"]
    lines += ["", f"## Stories: {len(report['stories']) - len(sg)} frames ready, {len(sg)} gaps", ""]
    lines += [f"- {s['id']}: needs {s['need']}" for s in sg]
    top = picker.uses.most_common(10)
    lines += ["", "## Most reused shots", ""] + [f"- {k}: {v}×" for k, v in top]
    unused = [s["shot_id"] for s in picker.shots if s["shot_id"] not in picker.uses]
    lines += ["", f"## Unused usable shots: {len(unused)}", "", ", ".join(unused[:80])]
    (BUILD / "compose_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok = sum(1 for e in report["reels"] if e["status"] == "ok")
    print(f"reels ok={ok} partial={sum(1 for e in report['reels'] if e['status'] == 'partial')} "
          f"gap={sum(1 for e in report['reels'] if e['status'] == 'gap')} → {(BUILD / 'compose_report.md').relative_to(ROOT)}")
