# Six-market localization

One English account, @monadavilla. Other markets get localized versions; there are no separate accounts.
Tourist arrivals tell us which markets know Bali. They don't measure demand for villas, so the split below gets re-weighted after week 1 using real Insights.

| Market | Language / version | Emotional angle | Where it runs | Reels to boost (Meta Ads) | Notes |
|---|---|---|---|---|---|
| **Australia** | English (AU/UK spelling: *metre, neighbour*) | Your own patch of Bali: space, garden, outdoor living, a second home a short flight away | Instagram, Facebook | R01, R03, R10, R11, R12 | Largest arrivals market. Lead with land and garden. Keep humour dry and understated. |
| **Singapore** | English | Privacy and calm away from the city, a house that's ready to live in, a transparent process | Instagram, Meta Ads | R08, R10, R13, R17 | Contrast with high-density living (R10 "Space over bedrooms"). On day 30, put clear process and documents first. |
| **China** | Simplified Chinese, burned-in subtitles (`--langs zh`) + 小红书 captions | Aesthetic life (生活美学), architecture, privacy, individuality | Xiaohongshu → WeChat for enquiries | R06, R14, R16, R17 | Instagram is not reachable in mainland China. Post 3–4 best cuts per week on Xiaohongshu with notes in diary style (vertical cover, title ≤20 characters). Use no sale or price words before day 30. Put a WeChat ID only in the day-30 materials. |
| **South Korea** | English + Korean subtitle test (`--langs ko`) | Minimalism, interiors, quiet daily ritual | Instagram (+ Naver Blog mirror for search) | R02, R06, R14, R16 | A/B test EN vs KO subtitle versions with a Trial Reel. Korean audiences save interior content, so watch Saves/Reach. |
| **India** | English | Spacious private home for the family, comfort, a holiday base | Instagram | R08, R09, R15, R10 | Family and gathering framing (R15 "Long lunches") with no staged people. Evening and golden-hour content. |
| **United Kingdom** | English (UK spelling) | Tropical modern design, relocation or a second home, escape from grey winters | Instagram, Facebook | R07, R11, R14, R19 | Rain and greenery content (R07) works well in the Nov–Feb UK winter. Keep the design language editorial. |

## Caption localization rules
- The hook and on-screen lines are translated in `campaign/localization.yaml`. A native speaker must review every line before publishing.
- Translate meaning, not words. A hook stays short: ≤ 14 Chinese characters and ≤ 20 Korean characters where possible.
- Numbers come from `facts.yaml` and stay in metric (m²). Use no currency before day 30.
- Hashtags stay English on Instagram. On Xiaohongshu use topics such as #巴厘岛 #巴厘岛别墅 #建筑美学 #慢生活, and add #巴厘岛房产 only on day 30.

## Day-30 per-market reply
The DM opener is in `strategy/instagram-sales-strategy-nov-2026.md` §8. A Chinese WeChat version and a Korean version need translation by a native speaker. Never send price, tenure or handover details that aren't marked `verified: true` in `facts.yaml`.
