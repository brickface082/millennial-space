# Our Millennial Space

**Live:** https://web-production-2e69f.up.railway.app  
**About:** https://web-production-2e69f.up.railway.app/about

A MySpace-era social network rebuilt for 2026 — custom profiles, Top 8, bulletins, photo albums, ICQ-style mail, crew (friends), profile comments, The Spot (local listings & events), polls, and daily quotes.

## Features

- Customizable profiles (colors, fonts, dark mode, profile song, BBCode)
- Top 8 crew grid and friend requests
- Direct messages + ICQ-style buddy window
- Photo albums and profile montages
- Profile comments with replies
- The Spot — geo-scoped Listing Space and Events Near Me
- Reusable invite links
- Journal (diary + public blog), polls, bulletins

## Stack

- Python / Flask / SQLAlchemy
- SQLite locally, PostgreSQL on Railway
- Cloudinary for media
- Deployed on Railway

## Local dev

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Tests: `python -m pytest tests/test_features.py -q`

## Growth / marketing

See [`marketing/GROWTH-PLAN.md`](marketing/GROWTH-PLAN.md) and [`marketing/OPENCLAW-CHANNEL.md`](marketing/OPENCLAW-CHANNEL.md).

## License

Private project — all rights reserved.