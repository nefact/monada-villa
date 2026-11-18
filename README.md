# Monada Villa: Archive to Story

A 30-day Instagram campaign for Monada Villa in Pererenan, Bali, built **only from the owner's existing photo and video archive**.
The output is 24 Reels plus the day-30 sale reveal, daily Stories and four carousels. Every Reel has an alternate hook cut, a cover, subtitles (EN/ZH/KO), shot-source references and a 30-day publication manifest.
Nothing is published automatically.

## Contents

| Path | What |
|---|---|
| `strategy/` | Original 30-day strategy (RU) and day-by-day calendar |
| `campaign/reels.yaml` | 24 Reels + R25 reveal: hooks A/B, on-screen lines, captions, shot *requirements*, fallback stories |
| `campaign/stories.yaml`, `carousels.yaml` | Daily Stories (with sticker notes) and 4 carousels |
| `campaign/facts.yaml` | **Property fact register.** Every claim in copy comes from here; unverified facts block publication |
| `campaign/localization.yaml`, `markets.md` | ZH/KO on-screen text and the six-market playbook (AU, SG, CN, KR, IN, UK) |
| `campaign/publication_manifest.{md,csv}` | Generated 30-day schedule with status, files, sources and blockers |
| `campaign/approvals.yaml` | Owner sign-off per item. Without it nothing is "ready to schedule" |
| `monada/` | The pipeline (Python + FFmpeg) |

## Workflow

```bash
pip install -r requirements.txt          # needs ffmpeg with libx264 + libass
# 0. copy originals into archive/ (git-ignored)
python -m monada ingest                  # 1–4 scan, scene-split videos, rate quality, de-duplicate,
                                         #     library/shot_index.csv + tags.csv + contact sheets
# 3b. classify: fill library/tags.csv (subject, lighting, shot_type, people_present, music_in_source,
#     may_be_outdated, crop_focus_x) by reviewing library/contact_sheets/ (Claude can do this pass)
python -m monada compose                 # 5   fill every template with real shots → build/specs, build/compose_report.md
python -m monada render --langs zh ko    # 6–7 out/reels (A/B, EN/ZH/KO), out/covers, out/subtitles, out/stories,
                                         #     out/carousels, *.qa.json crop/quality/age checks
python -m monada lint                    # compliance check of all copy (no media needed)
python -m monada manifest                # campaign/publication_manifest.md/.csv
python -m monada package                 # MONADA_CAMPAIGN/01_SOURCE_INDEX … 10_ANALYTICS (git-ignored)
```

### Delivery structure (`MONADA_CAMPAIGN/`)
| Folder | Contents |
|---|---|
| `01_SOURCE_INDEX` | `media_index.csv`: every shot with file, timestamps, tags, quality 1–10, story 1–10, duplicate/people/outdated flags, where it is used; plus contact sheets |
| `02_REELS` | `MONADA_D01_REEL_01.mp4` (hook A), `_B` (hook B), `_ZH` / `_KO` (burned-in subtitles) for the 23 pre-reveal Reels |
| `03_STORIES` | `MONADA_D01_STORY_1…3.mp4` + sticker notes per day |
| `04_CAROUSELS` | 4 × 1080×1350 carousels + caption |
| `05_COVERS` | `MONADA_D01_REEL_01_COVER.jpg` … |
| `06_CAPTIONS` | `MONADA_D01_CAPTION.txt`: hooks A/B, cover title, on-screen text, caption, CTA, 3–5 hashtags, audience, test time, unverified facts, sources with timestamps |
| `07_LOCALIZATIONS` | Xiaohongshu (ZH) and Korean captions for priority Reels, SRTs, market playbook |
| `08_PUBLISHING_CALENDAR` | 30-day calendar (CSV/MD) with approval and publishing status |
| `09_SALES_REVEAL` | Day-30 hero Reel (~39 s), cover, Stories, DM templates EN/ZH/KO, details carousel (DRAFT until facts are verified) |
| `10_ANALYTICS` | Tracking template; nothing pre-filled |

Audio: every item carries an original, generated ambient pad (no third-party rights) under the footage. Archive audio is muted because it appears to contain overlaid music. To use a licensed track, put it in `music/licensed/` with its licence file and set `music:` on the Reel. Alternatively, export without the bed and add a track from Instagram's licensed library at upload.

### What the pipeline does
- **Ingest:** reads EXIF and container dates (falling back to file date, which is flagged unreliable). Splits long videos into shots by scene detection. Rates each shot A/B/C/reject from sharpness, exposure and resolution, and records orientation, aspect ratio and audio. Finds exact duplicates (SHA-1) and near-duplicates (perceptual hash plus colour match) and keeps the best copy.
- **Compose:** picks the best-rated matching shots for each Reel slot. Each shot can be used at most 3 times, a hook shot is never reused as another Reel's hook, and repeat uses take a different segment of the same clip. If the archive lacks a scene (e.g. no rain or firepit footage), the Reel switches to its written **fallback story**. If that also fails, it is reported as a **gap**. Imagery is never generated.
- **Render:** 1080×1920, H.264 High, 30 fps, yuv420p, AAC 48 kHz, −14 LUFS, faststart.
  - Vertical and 4:3 sources fill the frame, with a slow pan on photos.
  - Horizontal 3:2 and 16:9 sources would lose more than 60% of the picture in a 9:16 crop, so they are shown whole on an editorial sand or charcoal frame instead.
  - The hook text appears at 0.15 s. Crossfades are 0.6 s with a light unified grade. Audio is the footage's natural sound. Licensed music only (`music/licensed/` + licence file).
- **QA per file:** resolution and codec, length (15–30 s, reveal ≤ 45 s), hook within 2 s, upscaled or framed shots, muted source audio, archive date of every shot, unverified facts, untranslated lines.

## Guardrails (enforced in code)
- No sale, price, investment or tenure wording before day 30 (`lint`, EN + ZH/KO).
- No ROI, yield or rental-income claims anywhere unless backed by evidence. No testimonials or reviews.
- Footage is never called "current". Every shot carries its capture date, and the reveal caption states that the footage is from the 2024–2025 archive.
- Shots tagged `people_present: y` (guests) are excluded. Shots with `music_in_source` set are muted.
- Unverified facts (`facts.yaml`) mark the item **BLOCKED** in the manifest. Items without owner approval stay "awaiting owner approval".
