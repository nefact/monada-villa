"""Compliance lint + 30-day publication manifest (works with or without rendered media)."""
from __future__ import annotations

import datetime as dt
import json
import re

from .common import BUILD, CAMPAIGN, OUT, ROOT, facts, load_yaml, resolve_facts, settings, write_csv

SALE = re.compile(r"\b(for sale|on sale|sale|selling|sell|sold|price[sd]?|asking|buy(?:er|ers|ing)?|invest\w*|"
                  r"listing|listed|offer|enquir\w*|inquir\w*|viewings?|freehold|leasehold|hak\s*pakai|title deed)\b", re.I)
FINANCE = re.compile(r"\b(roi|yield|guaranteed|returns?|rental income|occupancy|passive income|cash ?flow|profit)\b", re.I)
NOW = re.compile(r"\b(currently|current|right now|as it is today|recently (?:filmed|shot)|brand[- ]new|"
                 r"just (?:renovated|built|finished)|newly built|new build)\b", re.I)
TESTIMONIAL = re.compile(r"(guests? (?:say|said|love)|reviews?\b|★|5[- ]star|testimonial|\"[^\"]{8,}\"\s*[—-])", re.I)
CN_SALE = re.compile(r"(出售|售价|价格|投资|回报|房产出售|매매|매물|가격|투자|수익)")


def texts_of(item: dict, kind: str) -> list[tuple[str, str]]:
    out = []
    for k in ("hook", "alt_hook", "caption", "title", "end_text", "text", "sticker"):
        if item.get(k):
            out.append((k, item[k]))
    for i, sl in enumerate(item.get("slots", []) or []):
        if sl.get("text"):
            out.append((f"slot{i + 1}", sl["text"]))
    fb = item.get("fallback")
    if fb:
        out += [(f"fallback.{k}", v) for k, v in texts_of(fb, kind)]
    return out


def lint_item(item: dict, day: int, reveal_day: int, kind: str) -> tuple[list[str], list[str]]:
    errors, warns = [], []
    for field, raw in texts_of(item, kind):
        txt, _ = resolve_facts(raw)
        if day < reveal_day:
            for m in SALE.finditer(txt):
                errors.append(f"{field}: sale wording '{m.group(0)}' before day {reveal_day}")
            if CN_SALE.search(txt):
                errors.append(f"{field}: sale/finance wording (CJK) before day {reveal_day}")
        for m in FINANCE.finditer(txt):
            errors.append(f"{field}: financial claim '{m.group(0)}' — needs evidence, keep out of public copy")
        for m in NOW.finditer(txt):
            warns.append(f"{field}: '{m.group(0)}' — archive is 2024–2025, don't describe footage as current")
        if TESTIMONIAL.search(txt):
            errors.append(f"{field}: looks like a testimonial/review — none may be invented")
    return errors, warns


def lint_all(verbose: bool = True) -> dict:
    cfg = settings()
    rd = cfg["reveal_day"]
    res = {}
    for r in load_yaml("reels.yaml")["reels"]:
        res[r["id"]] = lint_item(r, r["day"], rd, "reel")
    for c in load_yaml("carousels.yaml")["carousels"]:
        res[c["id"]] = lint_item(c, c["day"], rd, "carousel")
    for st in load_yaml("stories.yaml")["stories"]:
        e, w = [], []
        for fr in st["frames"]:
            a, b = lint_item(fr, st["day"], rd, "story")
            e += a
            w += b
        res[f"D{st['day']:02d}_stories"] = (e, w)
    loc = load_yaml("localization.yaml") or {}
    for en, tr in (loc.get("strings") or {}).items():
        for lang, s in (tr or {}).items():
            if CN_SALE.search(s or "") and not loc.get("reveal_only", {}).get(en):
                res.setdefault("localization", ([], []))[0].append(f"{lang} '{s}': sale wording in a pre-reveal string")
    if verbose:
        ne = sum(len(e) for e, _ in res.values())
        nw = sum(len(w) for _, w in res.values())
        for k, (e, w) in res.items():
            for m in e:
                print(f"ERROR {k}: {m}")
            for m in w:
                print(f"warn  {k}: {m}")
        print(f"lint: {ne} error(s), {nw} warning(s)")
    return res


def build_manifest() -> None:
    cfg = settings()
    lint = lint_all(verbose=False)
    approvals = (load_yaml("approvals.yaml") or {}).get("approved", {}) if (CAMPAIGN / "approvals.yaml").exists() else {}
    start = cfg.get("start_date")
    start = dt.date.fromisoformat(str(start)) if start else None
    reels = {r["day"]: r for r in load_yaml("reels.yaml")["reels"]}
    cars = {c["day"]: c for c in load_yaml("carousels.yaml")["carousels"]}
    stories = {s["day"]: s for s in load_yaml("stories.yaml")["stories"]}
    ft = facts()
    cs = BUILD / "compose_status.json"
    compose_status = json.loads(cs.read_text()) if cs.exists() else {}
    rows = []
    for day in range(1, 31):
        r, c, st = reels.get(day), cars.get(day), stories.get(day)
        item = r or c
        kind = "Reel" if r else "Carousel" if c else "Stories only"
        iid = item["id"] if item else f"D{day:02d}"
        phase = ("Atmosphere & aspiration" if day <= 10 else "Architecture, lifestyle & trust" if day <= 20
                 else "Emotional story & anticipation" if day < 30 else "REVEAL")
        hook_a = resolve_facts(item.get("hook") or item.get("title", ""))[0] if item else ""
        hook_b = resolve_facts(item.get("alt_hook", ""))[0] if item else ""
        caption, fi = resolve_facts(item["caption"]) if item else ("", [])
        for f in (item or {}).get("facts", []):
            if not ft.get(f, {}).get("verified"):
                fi.append(f"{f}:unverified")
        fi = sorted(set(fi))
        tags = " ".join(cfg["hashtags_base"] + (item or {}).get("hashtags", [])) if item else ""
        story_plan = " · ".join(
            (fr.get("text") or (f"from {fr['from']}" if fr.get("from") else "/".join(fr.get("subject", []))))
            + (f" [{fr['sticker']}]" if fr.get("sticker") else "") for fr in (st or {}).get("frames", []))
        errs = list(lint.get(iid, ([], []))[0]) + list(lint.get(f"D{day:02d}_stories", ([], []))[0])
        warns = list(lint.get(iid, ([], []))[1])
        # rendered outputs / QA
        files, sources, qa_warn, spec_status = [], set(), [], ""
        if r:
            for v in ("A", "B"):
                p = OUT / "reels" / f"D{day:02d}_{r['id']}_{v}.mp4"
                if p.exists():
                    files.append(str(p.relative_to(ROOT)))
                    q = OUT / "reels" / f"D{day:02d}_{r['id']}_{v}.qa.json"
                    if q.exists():
                        qd = json.loads(q.read_text())
                        qa_warn += [w for w in qd["warnings"] if "owner to confirm" not in w]
                        sources |= {f"{s['shot_id']}:{s['file']}@{s['t_in']}" for s in qd["sources"]}
            sp = BUILD / "specs" / f"D{day:02d}_{r['id']}_A.json"
            if sp.exists():
                spec_status = json.loads(sp.read_text()).get("status", "")
        elif c:
            d = OUT / "carousels" / f"D{day:02d}_{c['id']}"
            if d.exists():
                files.append(str(d.relative_to(ROOT)) + "/")
            sp = BUILD / "specs" / f"D{day:02d}_{c['id']}.json"
            if sp.exists():
                spd = json.loads(sp.read_text())
                spec_status = spd["status"]
                sources |= {f"{s['shot_id']}:{s['file']}" for s in spd["slides"]}
        spec_status = compose_status.get(iid, spec_status)
        blocks = []
        if errs:
            blocks.append("lint errors")
        if fi:
            blocks.append("unverified facts")
        if spec_status == "gap":
            blocks.append("no suitable archive media")
        appr = approvals.get(iid)
        if blocks:
            status = "BLOCKED: " + ", ".join(blocks)
        elif not files:
            status = "to render" + (" (partial — some slots unfilled)" if spec_status == "partial" else "")
        elif not appr:
            status = "awaiting owner approval"
        else:
            status = "approved — ready to schedule"
        rows.append({
            "day": day, "date": (start + dt.timedelta(days=day - 1)).isoformat() if start else "",
            "time_wita": cfg.get("post_time_local", ""), "phase": phase, "format": kind, "id": iid,
            "title": (item or {}).get("title", "Stories: Q&A day") if item else "Stories: Q&A day",
            "hook_A": hook_a, "hook_B": hook_b, "caption": caption.strip(), "hashtags": tags,
            "stories": story_plan, "markets_boost": ",".join((r or {}).get("markets", [])),
            "files": " ".join(files), "sources": " ".join(sorted(sources)),
            "unverified_facts": ", ".join(fi), "lint": "; ".join(errs + warns), "qa": "; ".join(sorted(set(qa_warn))),
            "status": status, "owner_approved": f"{appr.get('by', '')} {appr.get('date', '')}".strip() if appr else "",
        })
    fields = list(rows[0])
    write_csv(CAMPAIGN / "publication_manifest.csv", rows, fields)
    md = ["# Monada Villa — 30-day publication manifest", "",
          "_Generated by `python -m monada manifest`. Nothing is published automatically: every item needs the owner's "
          "approval in `campaign/approvals.yaml`._", "",
          "| Day | Date | Format | ID | Hook A | Hook B | Stories | Status |", "|---|---|---|---|---|---|---|---|"]
    for x in rows:
        md.append(f"| {x['day']} | {x['date'] or '—'} | {x['format']} | {x['id']} | {x['hook_A']} | {x['hook_B']} | "
                  f"{x['stories']} | {x['status']} |")
    (CAMPAIGN / "publication_manifest.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    blocked = sum(1 for x in rows if x["status"].startswith("BLOCKED"))
    print(f"manifest: 30 days, {blocked} blocked → campaign/publication_manifest.csv / .md")
