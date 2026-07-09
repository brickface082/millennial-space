# Our Millennial Space — Zero-Budget Growth Plan

**Site:** https://web-production-2e69f.up.railway.app  
**GitHub:** https://github.com/brickface082/millennial-space  
**Pitch:** MySpace-era social network rebuilt for 2026 — custom profiles, Top 8, bulletins, photo albums, ICQ-style mail, The Spot (local listings & events), polls, daily quotes, reusable invite links.

**Constraints:** $0 spend. Legal only. No spam, no fake accounts, no vote manipulation, follow each platform's rules.

---

## Phase 1 — Make the link shareable (Grok / Coder)

| Step | Task | Owner | Status |
|------|------|-------|--------|
| 1.1 | Add meta description + Open Graph tags to `base.html` | Grok | pending |
| 1.2 | Add public `/about` landing page (no login required) | Grok | pending |
| 1.3 | Add `robots.txt` + `sitemap.xml` routes | Grok | pending |
| 1.4 | Polish GitHub repo README with screenshot + features | Grok | pending |

## Phase 2 — Write the copy (OpenClaw Research)

| Step | Task | Owner | Status |
|------|------|-------|--------|
| 2.1 | Draft Reddit posts (r/nostalgia, r/sideproject, r/InternetIsBeautiful) — check rules first | OpenClaw | pending |
| 2.2 | Draft Hacker News "Show HN" post | OpenClaw | pending |
| 2.3 | Draft Dev.to / Hashnode "building a MySpace revival" article | OpenClaw | pending |
| 2.4 | Draft 5 social posts (X/Bluesky/Mastodon tone) | OpenClaw | pending |
| 2.5 | Draft email blurb for friends (invite-link sharing) | OpenClaw | pending |

Save all drafts to `marketing/CONTENT/`.

## Phase 3 — Distribute (OpenClaw Main + Browser)

Try each step. On failure: 2 workarounds, then log skip and continue.

| Step | Task | Owner | Status |
|------|------|-------|--------|
| 3.1 | Research 15 free directories (AlternativeTo, SaaSHub, etc.) — list URLs + requirements | OpenClaw | pending |
| 3.2 | Submit to directories that need no paid tier (browser) | OpenClaw | pending |
| 3.3 | Post Show HN (needs Chris approval or OpenClaw browser if logged in) | OpenClaw | pending |
| 3.4 | Post to Reddit subs that allow self-promo (follow rules) | OpenClaw | pending |
| 3.5 | Find 10 Discord servers (indie hackers, web nostalgia) — draft intro message, do NOT spam | OpenClaw | pending |
| 3.6 | Cross-post article to Dev.to / Hashnode if free account possible | OpenClaw | pending |

## Phase 4 — Seed from inside (Chris + existing users)

| Step | Task | Owner | Status |
|------|------|-------|--------|
| 4.1 | Share personal invite link to 10 friends | Chris | pending |
| 4.2 | Ask early users to add 3 crew members each | Chris | pending |
| 4.3 | Post in any Facebook nostalgia groups Chris is already in | Chris | pending |

## Phase 5 — Measure (weekly)

| Metric | How |
|--------|-----|
| New signups | Railway logs / user count |
| Profile views | DB `profile_views` |
| Invite referrals | `InviteReferral` table |
| Traffic sources | Ask new users "how did you hear about us?" in welcome bulletin |

---

## OpenClaw communication

- **Drop tasks:** `C:\Users\brick\.openclaw\workspace\inbox\from-grok\ACTIVE.md`
- **Dispatch:** `marketing\send-to-openclaw.ps1 -Message "..."`  
- **Log results:** `marketing\STATUS.md` (append after each run)
- **Session key:** `millennial-space-growth` (persistent thread with Az)

## Failure log format

```
### [STEP ID] — FAILED
- Attempt 1: ...
- Attempt 2: ...
- Skipped. Next: ...
```