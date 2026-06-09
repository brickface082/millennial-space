# Millennial Space — Project Rules
# Based on McStoots Tech LLC Master SOP v3.0
# Full SOP: github.com/brickface082/McStoots-Master-Reference

---

## IDENTITY
You are Claude working with Chris McStoots (McStoots Tech LLC).
Owner: Chris | AI: Claude | Mode: BUILD MODE unless Chris says otherwise.

---

## THE FOUR LAWS (Karpathy — non-negotiable)

1. **THINK BEFORE CODING** — State assumptions explicitly. Surface ambiguity. Ask, never guess.
2. **SIMPLICITY FIRST** — Write minimum code that solves the stated problem. No unrequested abstractions.
3. **SURGICAL CHANGES** — Touch only what the request requires. Match existing style. Nothing else.
4. **GOAL-DRIVEN EXECUTION** — Define success criteria (Done When). Loop until verified. Then stop.

---

## STACK

| Layer | Tech |
|-------|------|
| Language | Python 3.12 |
| Framework | Flask + Flask-SQLAlchemy + Flask-Login + Flask-Bcrypt |
| Database (prod) | PostgreSQL on Railway |
| Database (test) | SQLite (in-memory via conftest.py) |
| Images | Cloudinary (CLOUDINARY_URL env var auto-configures) |
| Deployment | Railway (Procfile + railway.toml) |
| Tests | pytest — run: `python -m pytest tests/test_features.py -q` |

---

## FOLDER STRUCTURE

```
millennial-space/
├── app.py                  # entire Flask app — models, routes, migrations
├── CLAUDE.md               # this file
├── Procfile                # gunicorn entry point for Railway
├── railway.toml            # Railway build config
├── requirements.txt        # pinned dependencies
├── tests/
│   ├── conftest.py         # seeds test DB (brickface082 ID=1, testbot ID=3, testreceiver ID=4)
│   └── test_features.py    # full feature test suite (~113 checks across 18 tests)
├── templates/              # Jinja2 HTML templates (extends base.html)
└── static/                 # CSS, JS, images, uploads
```

---

## GATES — Nothing advances without clearing these

**Gate 1 — Scope:** Only requested files touched. No scope creep.
**Gate 2 — Real Code:** No mocks. No fake tests. Real implementation only.
**Gate 3 — Syntax:** Zero errors. Zero warnings. Consistent formatting.
**Gate 4 — Functional:** `python -m pytest tests/ -q` passes with 0 failures.
**Gate 5 — Cross-Review:** Review as if someone else wrote it. Find problems.
**Gate 6 — Proof:** All existing tests still pass + new tests for new features.

---

## STOP CONDITIONS

Claude stops and reports to Chris when:
- Same fix fails 3 times in a row (Three-Strike Rule)
- Context window reaches 70% — summarize state and flag it
- Blast radius is HIGH or CRITICAL and no backup exists

---

## PROJECT-SPECIFIC RULES (learned from past bugs)

### M010 — PostgreSQL migration isolation (CRITICAL)
Every `ALTER TABLE` migration must be in its **own** `with db.engine.connect() as conn:` block.
PostgreSQL aborts the ENTIRE transaction on any error — if two columns share a connection and
the first one already exists, the second will never be added. Each column = its own connection.

```python
# CORRECT
with db.engine.connect() as conn:
    if "new_col_1" not in existing:
        conn.execute(db.text("ALTER TABLE \"user\" ADD COLUMN new_col_1 TEXT DEFAULT ''"))
    conn.commit()

with db.engine.connect() as conn:
    if "new_col_2" not in existing:
        conn.execute(db.text("ALTER TABLE \"user\" ADD COLUMN new_col_2 INTEGER DEFAULT 0"))
    conn.commit()

# WRONG — never do this
with db.engine.connect() as conn:
    conn.execute(db.text("ALTER TABLE ..."))
    conn.execute(db.text("ALTER TABLE ..."))  # second ALTER can silently fail in PG
    conn.commit()
```

### M014 — JS variable injection in Jinja2 templates (CRITICAL)
Always use `| tojson` when injecting Python values into `<script>` blocks.
Jinja2 auto-escape turns `"` into `&#34;` inside script tags, causing a JS SyntaxError
that silently kills all function definitions on the page.

```html
<!-- CORRECT -->
<script>
  const username = {{ current_user.username | tojson }};
  const data = {{ some_dict | tojson }};
</script>

<!-- WRONG — breaks if value contains quotes, special chars, or is None -->
<script>
  const username = "{{ current_user.username }}";
</script>
```

### M009 — Jinja2 null crash in templates
Use `(value or 'fallback')` when rendering optional user fields in templates.
Existing users pre-dating a new column will have NULL — Jinja2 will crash or render "None".

```html
<!-- CORRECT -->
{{ (current_user.alert_sound or 'classic_beep') | tojson }}

<!-- WRONG -->
{{ current_user.alert_sound | tojson }}
```

### T001 — Image URL handling
Cloudinary URLs start with `http` — use them directly.
Legacy local filenames go through `url_for('static', filename=...)`.
The `image_url()` context processor handles this — use it in all templates.

### T005 — No HTML entities in script blocks (regression)
Run the script-rendering test to verify: it checks all `<script>` blocks for `&#NNN;` entities.
If entities appear, a `| tojson` filter is missing somewhere.

---

## MIGRATION TEMPLATE

Copy this exactly when adding a new column to any table:

```python
# ── [ColumnName] migration — separate connection (M010 SOP) ──────────────────
with db.engine.connect() as conn:
    if is_pg:
        existing = {row[0] for row in conn.execute(db.text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='tablename'"
        ))}
    else:
        existing = {row[1] for row in conn.execute(db.text("PRAGMA table_info('tablename')"))}
    if "column_name" not in existing:
        conn.execute(db.text("ALTER TABLE \"tablename\" ADD COLUMN column_name TYPE DEFAULT value"))
    conn.commit()
```

---

## TEST PROTOCOL

Every new feature gets tests in `tests/test_features.py`:
- Unauthenticated access (should redirect or block)
- Authenticated happy path
- Invalid input rejected
- DB state verified after action

Run before every commit:
```bash
python -m pytest tests/test_features.py -q
```

Expected output: `N passed, 0 failed`

---

## COMMIT FORMAT

```
feat: add [feature name]
fix: correct [what was wrong]
test: add [what is tested]
chore: [non-code change]
```

Subject under 50 chars. Imperative mood. Co-author line on Claude-assisted commits:
`Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

---

## KNOWN CONSTRAINTS

- No user-uploaded files go to disk on Railway (ephemeral filesystem) — always Cloudinary
- SQLite in tests, PostgreSQL in prod — migrations must handle both (check `is_pg` flag)
- `brickface082` is the hardcoded admin username (feedback admin, etc.)
- Test users: brickface082 (ID 1), placeholder_ms (ID 2), testbot (ID 3), testreceiver (ID 4)

---

## ANDON CORD — Pull immediately when:
- Known bug exists from previous task
- Three-strike rule fires
- Any test fails — build does not advance
- Blast radius is unacceptable without backup

*Full SOP: github.com/brickface082/McStoots-Master-Reference*
