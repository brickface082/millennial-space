# Grok ↔ OpenClaw Communication Channel

## Quick dispatch (PowerShell)

```powershell
cd C:\Users\brick\Desktop\millennial-space\marketing
.\send-to-openclaw.ps1 -File "C:\Users\brick\.openclaw\workspace\inbox\from-grok\ACTIVE.md"
```

Or a one-liner task:

```powershell
.\send-to-openclaw.ps1 -Message "Draft a Show HN post for Our Millennial Space and save to marketing/CONTENT/"
```

## Files

| Path | Purpose |
|------|---------|
| `marketing/GROWTH-PLAN.md` | Master plan (phases, steps, owners) |
| `marketing/STATUS.md` | Running log of what Grok + OpenClaw completed |
| `marketing/CONTENT/` | Drafts OpenClaw writes (Reddit, HN, social, etc.) |
| `marketing/send-to-openclaw.ps1` | CLI wrapper around `openclaw agent` |
| `.openclaw/workspace/inbox/from-grok/ACTIVE.md` | Current task queue for Az |

## OpenClaw session

- **Agent:** `main` (Az)
- **Session key:** `millennial-space-growth` (persistent thread)
- **Gateway:** `ws://127.0.0.1:18789` (must be running: `openclaw gateway run --force`)

## Telegram (alternative)

Chris can also message Az on Telegram (already paired) with:

> Run tasks in `inbox/from-grok/ACTIVE.md` for Millennial Space growth.

## Chris tonight

Check `marketing/STATUS.md` and `marketing/CONTENT/` for OpenClaw output. Blockers likely needing Chris:

- Reddit/HN posting (account login / karma)
- Personal invite blasts to friends
- Facebook group posts