"""Assemble rendered outputs into the MONADA_CAMPAIGN/ delivery structure (01…10) with brief-compliant names."""
from __future__ import annotations

import csv
import json
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

from .common import BUILD, CAMPAIGN, LIBRARY, OUT, ROOT, facts, load_shots, load_yaml, resolve_facts, settings, split_tags, write_csv
from .render import font, wrap

PKG = ROOT / "MONADA_CAMPAIGN"
DIRS = ["01_SOURCE_INDEX", "02_REELS", "03_STORIES", "04_CAROUSELS", "05_COVERS", "06_CAPTIONS",
        "07_LOCALIZATIONS", "08_PUBLISHING_CALENDAR", "09_SALES_REVEAL", "10_ANALYTICS"]

# Test windows: a starting hypothesis per primary market, to be replaced by Insights after week 1.
TIMES = {"AU": "16:30 WITA (19:30 AEDT)", "SG": "20:00 WITA (20:00 SGT)", "CN": "20:30 CST on Xiaohongshu",
         "KR": "20:00 WITA (21:00 KST)", "IN": "22:30 WITA (20:00 IST)", "UK": "03:30 WITA (19:30 GMT)"}
STORY_BASE = {"aerial": 10, "pool": 9, "exterior": 9, "garden": 8, "firepit": 8, "terrace": 8, "renovation": 7,
              "living": 7, "bedroom": 7, "dining": 7, "bathroom": 6, "kitchen": 6, "office": 6, "detail": 6,
              "entrance": 6, "neighbourhood": 7, "beach": 8}


def ratings(s: dict) -> tuple[int, int]:
    q10 = max(1, min(10, round(s["quality"] / 10)))
    subj = split_tags(s.get("subject"))
    if s.get("dup_of") or s.get("use", "y").lower() in ("n", "no") or s.get("people_present") in ("y", "yes"):
        return q10, 0
    st = max((STORY_BASE.get(x, 5) for x in subj), default=5)
    if "wide" in split_tags(s.get("shot_type")):
        st += 1
    if s["crop_retention"] < 0.4 and s["orientation"] != "vertical":
        st -= 1  # must be framed in 9:16
    st = round((st + q10) / 2) if q10 < 6 else st
    return q10, max(1, min(10, st))


def audience(day: int, markets: list[str]) -> str:
    seg = ("lifestyle & design followers (discovery)" if day <= 10 else
           "second-home seekers & design-led buyers (desire)" if day <= 20 else
           "engaged followers → prospective buyers (connection)" if day < 30 else "qualified buyers (enquiry)")
    return f"{seg}; primary {markets[0] if markets else 'AU'}" + (f", also {', '.join(markets[1:4])}" if len(markets) > 1 else "")


def cta(day: int) -> str:
    return ("Follow the Monada diary." if day <= 10 else "Save it for your future-home board." if day <= 20
            else "Follow the story." if day < 30 else "DM MONADA for property details.")


def copy(src: Path, dst: Path) -> bool:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    return False


def package() -> None:
    cfg = settings()
    ft = facts()
    if PKG.exists():
        shutil.rmtree(PKG)
    for d in DIRS:
        (PKG / d).mkdir(parents=True)
    reels = sorted(load_yaml("reels.yaml")["reels"], key=lambda r: r["day"])
    loc = load_yaml("captions_localized.yaml") or {}
    specs = {p.stem: json.loads(p.read_text()) for p in (BUILD / "specs").glob("*.json")}
    used_in = defaultdict(list)
    for name, sp in specs.items():
        for sh in sp.get("shots", []) + sp.get("slides", []):
            used_in[sh["shot_id"]].append(name)

    # 01 source index with 1–10 ratings
    shots = load_shots()
    rows = []
    for s in shots:
        q10, st10 = ratings(s)
        rows.append({"shot_id": s["shot_id"], "file": s["file"], "type": s["type"], "t_in": s["t_in"], "t_out": s["t_out"],
                     "width": int(s["width"]), "height": int(s["height"]), "orientation": s.get("orientation", ""),
                     "captured_at": s.get("captured_at", ""), "date_source": s.get("date_source", ""),
                     "subject": s.get("subject", ""), "lighting": s.get("lighting", ""), "shot_type": s.get("shot_type", ""),
                     "quality_1_10": q10, "story_1_10": st10, "grade": s.get("grade", ""), "duplicate_of": s.get("dup_of", ""),
                     "people_present": s.get("people_present", ""), "music_in_source": s.get("music_in_source", ""),
                     "may_be_outdated": s.get("may_be_outdated", ""), "use": s.get("use", ""), "notes": s.get("notes", ""),
                     "issues": s.get("issues", ""), "used_in": " ".join(sorted(set(used_in.get(s["shot_id"], []))))})
    rows.sort(key=lambda r: (-r["story_1_10"], -r["quality_1_10"]))
    write_csv(PKG / "01_SOURCE_INDEX" / "media_index.csv", rows, list(rows[0]))
    for p in sorted((LIBRARY / "contact_sheets").glob("*.jpg")):
        copy(p, PKG / "01_SOURCE_INDEX" / "contact_sheets" / p.name)
    copy(BUILD / "compose_report.md", PKG / "01_SOURCE_INDEX" / "compose_report.md")

    # 02 reels, 05 covers, 06 captions, 07 localizations
    cal = []
    for n, r in enumerate(reels, 1):
        d, base = r["day"], f"MONADA_D{r['day']:02d}_REEL_{n:02d}"
        sp = specs.get(f"D{d:02d}_{r['id']}_A", {})
        files = []
        for v, suf in (("A", ""), ("B", "_B")):
            for lang, ls in (("", ""), ("_zh", "_ZH"), ("_ko", "_KO")):
                stem = f"D{d:02d}_{r['id']}_{v}{lang}"
                target = PKG / ("09_SALES_REVEAL" if r.get("reveal") else "02_REELS") / f"{base}{suf}{ls}.mp4"
                if copy(OUT / "reels" / f"{stem}.mp4", target):
                    files.append(target.name)
                copy(OUT / "covers" / f"{stem}.jpg", PKG / "05_COVERS" / f"{base}{suf}{ls}_COVER.jpg")
                copy(OUT / "subtitles" / f"{stem}.srt", PKG / "07_LOCALIZATIONS" / "subtitles" / f"{base}{suf}{ls}.srt")
        caption, fi = resolve_facts(r["caption"])
        fi += [f"{f}:unverified" for f in r.get("facts", []) if not ft.get(f, {}).get("verified")]
        fi = sorted(set(fi))
        tags = cfg["hashtags_base"] + r.get("hashtags", [])
        onscreen = [t["text"].replace("\n", " / ") for t in sp.get("texts", [])]
        srcs = [f"{s['file']} @ {s['t_in']:.2f}s +{s['dur']:.2f}s" if s["type"] == "video" else s["file"]
                for s in sp.get("shots", [])]
        mk = r.get("markets", [])
        time = TIMES.get(mk[0] if mk else "AU")
        cover = resolve_facts(r.get("cover") or r["hook"])[0]
        txt = [f"{base} — {r['title']}  (day {d})", "",
               f"HOOK A: {resolve_facts(r['hook'])[0]}", f"HOOK B: {resolve_facts(r.get('alt_hook', ''))[0]}",
               f"COVER TITLE: {cover}", "ON-SCREEN TEXT:", *[f"  · {t}" for t in onscreen], "",
               "CAPTION:", caption.strip(), "", f"CTA: {cta(d)}", f"HASHTAGS: {' '.join(tags)}", "",
               f"AUDIENCE: {audience(d, mk)}", f"SUGGESTED TEST TIME: {time}",
               f"UNVERIFIED FACTS: {', '.join(fi) or 'none'}", "", "SOURCES:", *[f"  · {x}" for x in srcs], ""]
        (PKG / "06_CAPTIONS" / f"MONADA_D{d:02d}_CAPTION.txt").write_text("\n".join(txt), encoding="utf-8")
        if r["id"] in loc:
            L = loc[r["id"]]
            zh = L.get("zh", {})
            (PKG / "07_LOCALIZATIONS" / f"MONADA_D{d:02d}_ZH_xiaohongshu.txt").write_text(
                f"{zh.get('title', '')}\n\n{zh.get('body', '').strip()}\n\n{' '.join(zh.get('topics', []))}\n", encoding="utf-8")
            (PKG / "07_LOCALIZATIONS" / f"MONADA_D{d:02d}_KO_caption.txt").write_text(L.get("ko", "").strip() + "\n\n" + " ".join(tags) + "\n", encoding="utf-8")
        cal.append({"day": d, "format": "Reel", "id": r["id"], "topic": r["title"], "hook": resolve_facts(r["hook"])[0],
                    "alt_hook": resolve_facts(r.get("alt_hook", ""))[0], "caption_file": f"06_CAPTIONS/MONADA_D{d:02d}_CAPTION.txt",
                    "export": " ".join(files), "sources": " | ".join(srcs), "audience": audience(d, mk), "suggested_time": time,
                    "unverified_facts": ", ".join(fi), "approval_status": "pending owner", "publishing_status": "not scheduled"})

    # 04 carousels
    for n, c in enumerate(sorted(load_yaml("carousels.yaml")["carousels"], key=lambda c: c["day"]), 1):
        d = c["day"]
        dst = PKG / "04_CAROUSELS" / f"MONADA_D{d:02d}_CAROUSEL_{n:02d}"
        src = OUT / "carousels" / f"D{d:02d}_{c['id']}"
        if src.exists():
            shutil.copytree(src, dst)
        sp = specs.get(f"D{d:02d}_{c['id']}", {})
        cal.append({"day": d, "format": "Carousel", "id": c["id"], "topic": c["title"], "hook": c["title"], "alt_hook": "",
                    "caption_file": f"04_CAROUSELS/{dst.name}/caption.txt", "export": dst.name + "/",
                    "sources": " | ".join(s["file"] for s in sp.get("slides", [])), "audience": audience(d, ["AU", "KR", "CN"]),
                    "suggested_time": TIMES["AU"], "unverified_facts": "", "approval_status": "pending owner",
                    "publishing_status": "not scheduled"})

    # 03 stories
    for st in load_yaml("stories.yaml")["stories"]:
        d = st["day"]
        notes = []
        for k, fr in enumerate(st["frames"], 1):
            name = f"MONADA_D{d:02d}_STORY_{k}.mp4"
            folder = "09_SALES_REVEAL" if st.get("reveal") else "03_STORIES"
            copy(OUT / "stories" / f"D{d:02d}_S{k}.mp4", PKG / folder / name)
            notes.append(f"{name}: text “{resolve_facts(fr.get('text', ''))[0]}”" + (f"  + add sticker in app: {fr['sticker']}" if fr.get("sticker") else ""))
        (PKG / ("09_SALES_REVEAL" if st.get("reveal") else "03_STORIES") / f"MONADA_D{d:02d}_STORY_NOTES.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
        if not any(x["day"] == d for x in cal):
            cal.append({"day": d, "format": "Stories only", "id": f"D{d:02d}", "topic": "; ".join(n.split(": ", 1)[1] for n in notes),
                        "hook": "", "alt_hook": "", "caption_file": "", "export": f"03_STORIES/MONADA_D{d:02d}_STORY_*.mp4",
                        "sources": "", "audience": audience(d, ["AU"]), "suggested_time": TIMES["AU"], "unverified_facts": "",
                        "approval_status": "pending owner", "publishing_status": "not scheduled"})

    # 08 calendar
    cal.sort(key=lambda x: (x["day"], x["format"] != "Reel"))
    write_csv(PKG / "08_PUBLISHING_CALENDAR" / "MONADA_30_DAY_CALENDAR.csv", cal, list(cal[0]))
    md = ["# MONADA — 30-day publishing calendar", "", "Nothing is published, boosted or sent without the owner's approval. "
          "Times are test hypotheses, not data.", "",
          "| Day | Format | Topic | Hook | Export | Test time | Unverified | Approval |", "|---|---|---|---|---|---|---|---|"]
    md += [f"| {x['day']} | {x['format']} | {x['topic']} | {x['hook']} | {x['export'].split(' ')[0]} | {x['suggested_time']} | "
           f"{x['unverified_facts'] or '—'} | {x['approval_status']} |" for x in cal]
    (PKG / "08_PUBLISHING_CALENDAR" / "MONADA_30_DAY_CALENDAR.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    copy(CAMPAIGN / "markets.md", PKG / "07_LOCALIZATIONS" / "MARKETS_PLAYBOOK.md")

    # 09 sales reveal extras
    copy(CAMPAIGN / "dm_templates.md", PKG / "09_SALES_REVEAL" / "MONADA_D30_DM_TEMPLATES.md")
    reveal_details(PKG / "09_SALES_REVEAL" / "MONADA_D30_DETAILS_CAROUSEL_DRAFT", ft, cfg)
    (PKG / "09_SALES_REVEAL" / "CONFIDENTIAL.txt").write_text(
        "Day-30 materials. Do not post, share or tease before the approved reveal date.\n", encoding="utf-8")

    # 10 analytics (template only — no invented numbers)
    an = [{"day": x["day"], "id": x["id"], "format": x["format"], "variant": "", "market_boosted": "", "reach": "", "views": "",
           "avg_watch_time_s": "", "completion_rate": "", "shares": "", "saves": "", "profile_visits": "", "new_follows": "",
           "follows_per_profile_visit": "", "dms": "", "qualified_enquiries": "", "notes": ""} for x in cal]
    write_csv(PKG / "10_ANALYTICS" / "MONADA_TRACKING.csv", an, list(an[0]))
    (PKG / "10_ANALYTICS" / "README.md").write_text(
        "# Tracking\n\nFill from Instagram Insights (and Xiaohongshu for CN) 48 h and 7 days after each post. "
        "Compare A/B hooks with Trial Reels. Judge by shares/reach, saves/reach, follows per profile visit and — after day 30 — "
        "qualified enquiries, not views alone. No figures are pre-filled.\n", encoding="utf-8")
    n_mp4 = len(list(PKG.rglob("*.mp4")))
    print(f"packaged → {PKG.relative_to(ROOT)}/  ({n_mp4} videos, {len(cal)} calendar rows)")


def reveal_details(dst: Path, ft: dict, cfg: dict) -> None:
    """Day-30 details carousel. Unverified values are shown as [UNVERIFIED …] and the slides carry a DRAFT mark."""
    dst.mkdir(parents=True, exist_ok=True)
    W, H = 1080, 1350
    sand, ink = cfg["render"]["frame_bg_light"], (42, 42, 42)

    def val(k, label):
        f = ft.get(k, {})
        if not f.get("value"):
            return f"[{label} — TO BE CONFIRMED]"
        return f["value"] + ("" if f.get("verified") else "  [UNVERIFIED]")
    slides = [
        ("MONADA VILLA", ["A private tropical home", val("location", "LOCATION")]),
        ("Key facts", [f"Land: {val('land_area', 'LAND')}", f"Building: {val('house_area', 'BUILDING AREA')}",
                       f"Bedrooms: {val('bedrooms', 'BEDROOMS')}", f"Pool: {val('pool', 'POOL')}", f"Study: {val('home_office', 'STUDY')}",
                       f"Garden: {val('garden', 'GARDEN')}", f"Parking: {val('parking', 'PARKING')}"]),
        ("Floor plan", ["[FLOOR PLAN — owner to supply]"]),
        ("Tenure & handover", [f"Tenure: {val('tenure', 'TENURE (from documents)')}", f"Current lease until: {val('tenancy_until', 'LEASE')}"]),
        ("Asking price", [val("asking_price", "ASKING PRICE")]),
        ("Private viewings", ["By appointment", "DM MONADA for property details"]),
    ]
    draft = not all(ft.get(k, {}).get("verified") for k in ("location", "land_area", "house_area", "bedrooms", "tenure", "asking_price"))
    for i, (title, lines) in enumerate(slides, 1):
        im = Image.new("RGB", (W, H), sand)
        d = ImageDraw.Draw(im)
        ft_t, ft_b = font("Inter Light", 64), font("Inter Light", 40)
        d.text((90, 160), title, font=ft_t, fill=ink)
        y = 320
        for ln in lines:
            for w in wrap(ln, ft_b, W - 180, d):
                d.text((90, y), w, font=ft_b, fill=ink)
                y += 58
            y += 18
        d.text((90, H - 110), "M O N A D A", font=font("Inter ExtraLight", 30), fill=ink)
        if draft:
            d.text((W - 400, H - 110), "DRAFT — NOT FOR PUBLICATION", font=font("Inter Medium", 22), fill=(170, 40, 40))
        im.save(dst / f"{i:02d}.jpg", quality=93)
