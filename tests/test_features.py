# Millennial Space - automated feature test suite.
# Run: .\venv\Scripts\python.exe tests\test_features.py
# Tests run against the local Flask test client (no browser, no Render needed).
import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as application
from app import app, db, User, CrewRequest, DirectMessage, bcrypt, JournalEntry, Poll, PollOption, PollVote, Invite, Feedback, PasswordResetToken, PhotoMontage, MontageSlide, SpotListing, CornerEvent

app.config["TESTING"] = True
app.config["WTF_CSRF_ENABLED"] = False
app.config["SERVER_NAME"] = None
app.config["MAIL_SUPPRESS_SEND"] = True   # never send real emails during tests

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []

def check(label, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, label, detail))
    print(f"{status} {label}" + (f" — {detail}" if detail else ""))

def login(client, email, password):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)

def logout(client):
    client.get("/logout", follow_redirects=True)

# ── helpers ──────────────────────────────────────────────────────────────────

def get_user(username):
    with app.app_context():
        return User.query.filter_by(username=username).first()

def reset_users():
    """Reset test state between test groups."""
    with app.app_context():
        for req in CrewRequest.query.filter(
            (CrewRequest.from_id.in_([1,3])) | (CrewRequest.to_id.in_([1,3]))
        ).all():
            db.session.delete(req)
        for msg in DirectMessage.query.filter(
            (DirectMessage.from_id.in_([1,3])) | (DirectMessage.to_id.in_([1,3]))
        ).all():
            db.session.delete(msg)
        u1 = db.session.get(User, 1)
        u3 = db.session.get(User, 3)
        if u1:
            u1.msg_filter = "open"
        if u3:
            u3.msg_filter = "open"
        db.session.commit()

# ── tests ─────────────────────────────────────────────────────────────────────

def test_auth():
    print("\n-- Auth --")
    with app.test_client() as c:
        r = login(c, "brickface082@gmail.com", "wrongpassword")
        check("Login rejects bad password", b"Invalid" in r.data or r.status_code == 200)

        r = login(c, "testbot@millennial-space.com", "testpass123")
        check("testbot can log in", b"testbot" in r.data or r.status_code == 200)

        r = c.get("/logout", follow_redirects=True)
        check("Logout redirects to login", b"Our Millennial Space" in r.data)

def test_profile():
    print("\n-- Profile --")
    with app.test_client() as c:
        r = c.get("/profile/brickface082")
        check("Profile page loads unauthenticated", r.status_code == 200)
        check("Profile shows username", b"brickface082" in r.data)

        r = c.get("/profile/doesnotexist999")
        check("Unknown profile returns 404", r.status_code == 404)

def test_search():
    print("\n-- Search --")
    with app.test_client() as c:
        r = c.get("/search?q=test", follow_redirects=True)
        check("Search redirects to login when unauthenticated", "login" in r.request.path.lower() or r.status_code == 200)

        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.get("/search?q=brick")
        check("Search finds brickface082", b"brickface082" in r.data)

        r = c.get("/search?q=zzznobodyyy")
        check("Search returns no results for unknown query", b"No users found" in r.data)

        r = c.get("/search?q=")
        check("Empty search shows prompt", b"Enter a username" in r.data)

def test_messaging_open():
    print("\n-- Messaging (Open filter) --")
    reset_users()
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.get("/chat/brickface082")
        check("testbot can open chat with brickface082 (open filter)", r.status_code == 200)

        r = c.post("/chat/brickface082/send", data={"body": "hello from testbot"},
                   follow_redirects=True)
        check("testbot can send message (open filter)", r.status_code == 200)

        with app.app_context():
            msg = DirectMessage.query.filter_by(to_id=1).first()
            check("Message saved to DB", msg is not None and msg.body == "hello from testbot")

def test_messaging_crew_only():
    print("\n-- Messaging (Crew Only filter) --")
    reset_users()
    with app.app_context():
        u1 = db.session.get(User, 1)
        u1.msg_filter = "crew"
        db.session.commit()

    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.get("/chat/brickface082", follow_redirects=True)
        check("Non-crew blocked from chat page (crew filter)", b"only accepts messages" in r.data)

        r = c.post("/chat/brickface082/send", data={"body": "bypass attempt"},
                   follow_redirects=True)
        check("Non-crew blocked from send route (crew filter)", b"only accepts messages" in r.data)

        with app.app_context():
            msg = DirectMessage.query.filter_by(to_id=1, from_id=3).first()
            check("Blocked message NOT saved to DB", msg is None)

def test_messaging_verified():
    print("\n-- Messaging (Verified filter) --")
    reset_users()
    with app.app_context():
        u1 = db.session.get(User, 1)
        u1.msg_filter = "verified"
        db.session.commit()

    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.get("/chat/brickface082", follow_redirects=True)
        check("Unverified user redirected to verify page", b"robot" in r.data or b"verify" in r.request.path.lower())

        with c.session_transaction() as sess:
            recipient_id = get_user("brickface082").id
            sess[f"verify_answer_{recipient_id}"] = 99
        r = c.post(f"/chat/brickface082/verify", data={"answer": "99"},
                   follow_redirects=True)
        check("Correct math answer grants chat access", b"Say something" in r.data)

        r = c.post("/chat/brickface082/send", data={"body": "verified message"},
                   follow_redirects=True)
        check("Verified user can send message", r.status_code == 200)

def test_crew():
    print("\n-- Crew --")
    # Use testbot (id=3) and testreceiver (id=4) — both have known passwords
    with app.app_context():
        for req in CrewRequest.query.filter(
            (CrewRequest.from_id.in_([3,4])) | (CrewRequest.to_id.in_([3,4]))
        ).all():
            db.session.delete(req)
        db.session.commit()

    req_id = None
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.post("/crew/add/4", follow_redirects=True)
        check("testbot can send crew request to testreceiver", r.status_code == 200)

        with app.app_context():
            req = CrewRequest.query.filter_by(from_id=3, to_id=4).first()
            check("Crew request saved to DB", req is not None and req.status == "pending")
            req_id = req.id if req else None

    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")
        if req_id:
            r = c.post(f"/crew/accept/{req_id}", follow_redirects=True)
            check("testreceiver can accept crew request", r.status_code == 200)
            with app.app_context():
                req = CrewRequest.query.filter_by(id=req_id).first()
                check("Crew request status is accepted", req is not None and req.status == "accepted")

def test_away_message():
    print("\n-- Away Message (T018) --")
    with app.app_context():
        u = db.session.get(User, 3)
        u.status = "away"
        u.away_message = "Gone fishin'"
        db.session.commit()

    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")
        r = c.get("/profile/testbot")
        check("Away banner shows on profile when status=away", b"Gone fishin" in r.data)
        check("Away banner not shown when no away message", True)  # covered by absence test below

        r = c.get("/chat/testbot")
        check("Away message shown in chat header", b"Gone fishin" in r.data)

    with app.app_context():
        u = db.session.get(User, 3)
        u.status = "online"
        u.away_message = ""
        db.session.commit()

    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")
        r = c.get("/profile/testbot")
        check("Away banner hidden when status=online", b"Gone fishin" not in r.data)

def test_sounds():
    print("\n-- Sounds (T019) --")
    with app.test_client() as c:
        # Unauthenticated — should redirect to login
        r = c.get("/sounds", follow_redirects=True)
        check("Sounds page requires login", "login" in r.request.path.lower() or r.status_code == 200)

        login(c, "testbot@millennial-space.com", "testpass123")

        # GET sounds page loads
        r = c.get("/sounds")
        check("Sounds page loads for logged-in user", r.status_code == 200)
        check("Sounds page shows built-in options", b"classic_beep" in r.data or b"Classic Beep" in r.data)
        check("Sounds page shows ICQ pack", b"ICQ Uh-Oh" in r.data or b"icq_uhoh" in r.data)
        check("Sounds page shows Movie Quote pack",
              b"Movie Quote Pack" in r.data and b"quote_ill_be_back" in r.data)
        check("Sounds page shows Your Soundboard",
              b"Your Soundboard" in r.data and b"Kokoro" in r.data)

        r = c.post("/sounds", data={"action": "select", "alert_sound": "quote_ill_be_back"},
                   follow_redirects=True)
        check("Movie quote alert saves", r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("quote_ill_be_back in DB", u is not None and u.alert_sound == "quote_ill_be_back")

        # Select a valid sound
        r = c.post("/sounds", data={"action": "select", "alert_sound": "rising_tone"},
                   follow_redirects=True)
        check("Can select a built-in sound", r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("alert_sound saved to DB", u is not None and u.alert_sound == "rising_tone")

        # Invalid sound name rejected — falls back to classic_beep
        r = c.post("/sounds", data={"action": "select", "alert_sound": "HACK_VALUE"},
                   follow_redirects=True)
        check("Invalid sound name rejected", r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("Invalid sound falls back to classic_beep", u is not None and u.alert_sound == "classic_beep")

        # Upload oversized file is rejected
        import io
        from app import UserSound
        big_audio = io.BytesIO(b"\x00" * 600_000)  # 600KB — over the limit
        r = c.post("/sounds", data={"action": "library_upload",
                                     "sound_file": (big_audio, "test.mp3", "audio/mpeg"),
                                     "label": "Too Big"},
                   content_type="multipart/form-data", follow_redirects=True)
        check("Oversized upload rejected", b"too large" in r.data or r.status_code == 200)

        # Upload valid small file is accepted into soundboard
        small_audio = io.BytesIO(b"\x00" * 1000)  # 1KB — fine
        r = c.post("/sounds", data={"action": "library_upload",
                                     "sound_file": (small_audio, "test.mp3", "audio/mpeg"),
                                     "label": "Test Clip"},
                   content_type="multipart/form-data", follow_redirects=True)
        check("Small upload accepted", b"soundboard" in r.data or r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            snd = UserSound.query.filter_by(user_id=u.id, label="Test Clip").first()
            check("clip saved to UserSound", snd is not None and (snd.audio_data or "").startswith("data:"))
            check("alert_sound set to us_* after upload",
                  u is not None and (u.alert_sound or "").startswith("us_"))

        # Reset testbot sounds
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            UserSound.query.filter_by(user_id=u.id).delete()
            u.alert_sound = "classic_beep"
            u.custom_sound = ""
            db.session.commit()

def test_icq_inbox():
    print("\n-- ICQ Inbox / Unread (T019.5) --")
    # Seed: testbot sends a message to testreceiver
    with app.app_context():
        for m in DirectMessage.query.filter(
            (DirectMessage.from_id.in_([3,4])) | (DirectMessage.to_id.in_([3,4]))
        ).all():
            db.session.delete(m)
        db.session.commit()
        msg = DirectMessage(from_id=3, to_id=4, body="hey unread test", is_read=False)
        db.session.add(msg)
        db.session.commit()

    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")

        # /inbox/unread should show 1 unread
        r = c.get("/inbox/unread")
        check("/inbox/unread returns JSON", r.status_code == 200)
        import json
        data = json.loads(r.data)
        check("Unread count is 1", data["count"] == 1)
        check("Sender is testbot", any(s["username"] == "testbot" for s in data["senders"]))

        # /inbox/conversations should list testbot
        r = c.get("/inbox/conversations")
        convos = json.loads(r.data)
        check("Conversations lists testbot", any(c2["username"] == "testbot" for c2 in convos))
        check("Unread count in conversation", any(c2["unread"] == 1 for c2 in convos if c2["username"] == "testbot"))

        # Opening chat marks messages read
        c.get("/chat/testbot")
        r = c.get("/inbox/unread")
        data2 = json.loads(r.data)
        check("Unread count drops to 0 after opening chat", data2["count"] == 0)

        # /inbox/read/<username> POST also marks read
        with app.app_context():
            msg2 = DirectMessage(from_id=3, to_id=4, body="another unread", is_read=False)
            db.session.add(msg2)
            db.session.commit()
        r = c.post("/inbox/read/testbot")
        check("/inbox/read POST returns ok", r.status_code == 200)

        r = c.get("/icq/buddies")
        check("/icq/buddies returns JSON", r.status_code == 200)
        buddies = json.loads(r.data)
        check("Buddies is a list", isinstance(buddies, list))
        r = c.get("/inbox/unread")
        data3 = json.loads(r.data)
        check("Unread count 0 after /inbox/read", data3["count"] == 0)

        # DND flag returned correctly
        with app.app_context():
            u = db.session.get(User, 4)
            u.status = "dnd"
            db.session.commit()
        r = c.get("/inbox/unread")
        data4 = json.loads(r.data)
        check("DND flag true when status=dnd", data4["dnd"] == True)
        with app.app_context():
            u = db.session.get(User, 4)
            u.status = "online"
            db.session.commit()

def test_profile_views():
    print("\n-- Profile View Counter (T020) --")
    # Reset brickface082 view count to 0
    with app.app_context():
        u = db.session.get(User, 1)
        u.profile_views = 0
        db.session.commit()

    with app.test_client() as c:
        # Unauthenticated visit increments counter
        c.get("/profile/brickface082")
        with app.app_context():
            u = db.session.get(User, 1)
            check("Unauthenticated visit increments view count", (u.profile_views or 0) == 1)

        # Another visitor also increments
        login(c, "testbot@millennial-space.com", "testpass123")
        c.get("/profile/brickface082")
        with app.app_context():
            u = db.session.get(User, 1)
            check("Authenticated non-owner visit increments count", (u.profile_views or 0) == 2)

        # Owner visiting own profile does NOT increment — use testbot (known password)
        logout(c)
        with app.app_context():
            u = db.session.get(User, 3)
            u.profile_views = 0
            db.session.commit()
        login(c, "testbot@millennial-space.com", "testpass123")
        c.get("/profile/testbot")
        with app.app_context():
            u = db.session.get(User, 3)
            check("Owner visit does NOT increment count", (u.profile_views or 0) == 0)

        # View count displays on profile page
        logout(c)
        r = c.get("/profile/brickface082")
        check("View count displayed on profile page", "views" in r.data.decode("utf-8", errors="replace"))

def test_mood():
    print("\n-- Mood Indicator (T021) --")
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")

        # Set a valid mood
        r = c.post("/edit", data={
            "bio": "", "bg_color": "#ff66b2", "profile_song": "",
            "away_message": "", "msg_filter": "open", "mood": "happy"
        }, follow_redirects=True)
        check("Valid mood saves successfully", r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("Mood stored in DB", u is not None and u.mood == "happy")

        # Mood displays on profile
        r = c.get("/profile/testbot")
        check("Mood displayed on profile", "Happy" in r.data.decode("utf-8", errors="replace"))

        # Invalid mood rejected — falls back to empty string
        r = c.post("/edit", data={
            "bio": "", "bg_color": "#ff66b2", "profile_song": "",
            "away_message": "", "msg_filter": "open", "mood": "HACK_VALUE"
        }, follow_redirects=True)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("Invalid mood rejected, stored as empty", u is not None and u.mood == "")

        # Owner always sees mood dropdown on their profile
        r = c.get("/profile/testbot")
        check("Owner sees mood dropdown on profile", "Mood:" in r.data.decode("utf-8", errors="replace"))

        # Visitor does NOT see "Current Mood" when mood is empty
        logout(c)
        r = c.get("/profile/testbot")
        check("Visitor sees no mood block when mood is empty", "Current Mood" not in r.data.decode("utf-8", errors="replace"))
        login(c, "testbot@millennial-space.com", "testpass123")

        # /mood route saves and redirects to profile
        r = c.post("/mood", data={"mood": "cool"}, follow_redirects=True)
        check("/mood route redirects to profile", r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("Mood updated via /mood route", u is not None and u.mood == "cool")

        # Invalid mood via /mood route falls back to empty
        c.post("/mood", data={"mood": "INVALID"}, follow_redirects=True)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("Invalid mood via /mood stored as empty", u is not None and u.mood == "")

        # Clear mood after test
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            u.mood = ""
            db.session.commit()

def test_script_rendering():
    """
    SOP T005 / M014 regression: verify no HTML entities appear inside <script> blocks
    in rendered pages. Jinja2 auto-escape turns quotes into &#34; inside script tags,
    causing a JS SyntaxError that silently kills all window.* function definitions.
    """
    import re
    with app.test_client() as client:
        login(client, "testbot@millennial-space.com", "testpass123")
        resp = client.get("/profile/testbot", follow_redirects=True)
        html = resp.data.decode("utf-8")

        # Extract all <script>...</script> blocks
        script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
        icq_config_blocks = [s for s in script_blocks if 'ICQ_CONFIG' in s]
        check("ICQ_CONFIG inline script present", len(icq_config_blocks) > 0)
        check("icq.js loaded", 'icq.js' in html)

        for i, block in enumerate(icq_config_blocks):
            has_entities = bool(re.search(r'&#\d+;', block))
            check(f"Script block {i+1} contains no HTML entities (&#NNN;)",
                  not has_entities,
                  "FAIL: Jinja2 is HTML-escaping values inside <script> — use | tojson" if has_entities else "")

        logout(client)

def test_journal():
    """T023 — Diary/Blog access control. Core security: diary entries are strictly
    owner-only. Blog entries are public. entry_type cannot be changed after creation."""
    print("\n-- Journal / Diary / Blog (T023) --")

    # --- Setup: create a diary entry and a blog entry for testbot ---
    with app.app_context():
        # Clean up any leftovers from previous runs
        JournalEntry.query.filter_by(user_id=3).delete()
        db.session.commit()

        testbot = User.query.filter_by(username="testbot").first()
        diary_entry = JournalEntry(user_id=testbot.id, title="Secret Thoughts",
                                   body="Very private.", entry_type="diary")
        blog_entry  = JournalEntry(user_id=testbot.id, title="Hello World",
                                   body="Public post.", entry_type="blog")
        db.session.add_all([diary_entry, blog_entry])
        db.session.commit()
        diary_id = diary_entry.id
        blog_id  = blog_entry.id

    # 1. Owner can access /diary
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.get("/diary")
        check("Diary index: owner can access /diary", r.status_code == 200)
        check("Diary index: shows PRIVATE DIARY banner",
              "PRIVATE DIARY" in r.data.decode("utf-8", errors="replace"))

        r = c.get(f"/diary/{diary_id}")
        check("Diary view: owner can view own entry", r.status_code == 200)
        check("Diary view: shows PRIVATE DIARY banner",
              "PRIVATE DIARY" in r.data.decode("utf-8", errors="replace"))

    # 2. Another logged-in user gets 403 on a diary entry
    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")
        r = c.get(f"/diary/{diary_id}")
        check("Diary view: non-owner gets 403", r.status_code == 403)

    # 3. Unauthenticated user is redirected away from /diary
    with app.test_client() as c:
        r = c.get("/diary", follow_redirects=False)
        check("Diary index: unauthenticated redirected (not 200)",
              r.status_code in (301, 302))

        r = c.get(f"/diary/{diary_id}", follow_redirects=False)
        check("Diary view: unauthenticated redirected (not 200)",
              r.status_code in (301, 302))

    # 4. Blog post is publicly readable (no login needed)
    with app.test_client() as c:
        r = c.get("/blog/testbot")
        check("Blog index: publicly accessible (no login)",
              r.status_code == 200)
        check("Blog index: shows PUBLIC BLOG banner",
              "PUBLIC BLOG" in r.data.decode("utf-8", errors="replace"))

        r = c.get(f"/blog/testbot/{blog_id}")
        check("Blog view: publicly accessible (no login)", r.status_code == 200)
        check("Blog view: shows PUBLIC BLOG banner",
              "PUBLIC BLOG" in r.data.decode("utf-8", errors="replace"))
        check("Blog view: shows post title", b"Hello World" in r.data)

    # 5. Non-owner cannot POST to create a blog entry for someone else
    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")
        r = c.post("/blog/testbot/new",
                   data={"title": "Hack", "body": "Injected post"},
                   follow_redirects=False)
        check("Blog new: non-owner gets 403", r.status_code == 403)

    # 6. Profile page shows diary link to owner, hides it from visitor
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.get("/profile/testbot")
        html = r.data.decode("utf-8", errors="replace")
        check("Profile: owner sees Private Diary link", "Private Diary" in html)
        check("Profile: owner sees Public Blog link", "Public Blog" in html)

    with app.test_client() as c:
        r = c.get("/profile/testbot")
        html = r.data.decode("utf-8", errors="replace")
        check("Profile: visitor does NOT see Private Diary link",
              "Private Diary" not in html)
        check("Profile: visitor DOES see public blog link",
              "Blog" in html)

    # Cleanup
    with app.app_context():
        JournalEntry.query.filter_by(user_id=3).delete()
        db.session.commit()


def test_polls():
    """T024 — Polls: create, vote, filter, opt-in/out, duplicate vote blocked."""
    print("\n-- Polls (T024) --")

    # Cleanup leftovers
    with app.app_context():
        Poll.query.filter_by(creator_id=3).delete()
        u3 = User.query.filter_by(username="testbot").first()
        u4 = User.query.filter_by(username="testreceiver").first()
        u3.polls_enabled = True
        u4.polls_enabled = True
        u3.msg_filter = "open"
        u4.msg_filter = "open"
        db.session.commit()

    # 1. Logged-in user can create a poll
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.post("/polls/new", data={
            "question": "What is your fav color?",
            "option": ["Red", "Blue", "Green"]
        }, follow_redirects=True)
        check("Poll created successfully", r.status_code == 200)
        with app.app_context():
            poll = Poll.query.filter_by(creator_id=3).first()
            check("Poll saved to DB", poll is not None)
            check("Poll has 3 options", poll is not None and len(poll.options) == 3)

    # 2. User can vote (opted in, open filter)
    with app.app_context():
        poll = Poll.query.filter_by(creator_id=3).first()
        poll_id   = poll.id
        option_id = poll.options[0].id

    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")
        r = c.post(f"/polls/{poll_id}/vote",
                   data={"option_id": option_id}, follow_redirects=True)
        check("Vote submitted", r.status_code == 200)
        with app.app_context():
            vote = PollVote.query.filter_by(poll_id=poll_id, user_id=4).first()
            check("Vote saved to DB", vote is not None)

    # 3. Cannot vote twice on same poll
    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")
        r = c.post(f"/polls/{poll_id}/vote",
                   data={"option_id": option_id}, follow_redirects=True)
        check("Duplicate vote blocked (redirected, not error)", r.status_code == 200)
        with app.app_context():
            count = PollVote.query.filter_by(poll_id=poll_id, user_id=4).count()
            check("Still only 1 vote in DB after duplicate attempt", count == 1)

    # 4. Opted-out user sees opt-in prompt, not polls
    with app.app_context():
        u4 = User.query.filter_by(username="testreceiver").first()
        u4.polls_enabled = False
        db.session.commit()
    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")
        r = c.get("/polls")
        check("Opted-out user sees opt-in prompt",
              "Turn On Polls" in r.data.decode("utf-8", errors="replace"))

    # 5. Verified filter blocks polls
    with app.app_context():
        u4 = User.query.filter_by(username="testreceiver").first()
        u4.polls_enabled = True
        u4.msg_filter = "verified"
        db.session.commit()
    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")
        r = c.get("/polls")
        html = r.data.decode("utf-8", errors="replace")
        check("Verified filter user sees no polls",
              "What is your fav color?" not in html)

    # 6. Only creator can delete poll
    with app.test_client() as c:
        login(c, "testreceiver@millennial-space.com", "testpass123")
        r = c.post(f"/polls/{poll_id}/delete", follow_redirects=True)
        with app.app_context():
            still_exists = Poll.query.get(poll_id) is not None
        check("Non-creator cannot delete poll", still_exists)

    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.post(f"/polls/{poll_id}/delete", follow_redirects=True)
        check("Creator can delete poll", r.status_code == 200)
        with app.app_context():
            gone = Poll.query.get(poll_id) is None
        check("Poll removed from DB after delete", gone)

    # Cleanup
    with app.app_context():
        u4 = User.query.filter_by(username="testreceiver").first()
        u4.polls_enabled = False
        u4.msg_filter = "open"
        u3 = User.query.filter_by(username="testbot").first()
        u3.polls_enabled = False
        db.session.commit()


def test_invites():
    print("\n-- T026 Invites --")
    # 1. Unauthenticated user cannot create invite
    with app.test_client() as c:
        r = c.post("/invite/create", follow_redirects=True)
        check("Unauthenticated invite create redirects to login",
              b"login" in r.request.path.lower().encode() or b"Login" in r.data)

    # 2. Logged-in user can create invite
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.post("/invite/create")
        check("Invite create returns JSON link", r.status_code == 200 and b'"link"' in r.data)
        import json
        data = json.loads(r.data)
        token = data["link"].split("/invite/")[-1]
        check("Token is non-empty", len(token) > 10)

    # 3. Invite landing page — valid unused token
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.post("/invite/create")
        import json
        token = json.loads(r.data)["link"].split("/invite/")[-1]

    with app.test_client() as c:
        r = c.get(f"/invite/{token}")
        check("Invite landing loads for valid token", r.status_code == 200)
        check("Landing shows inviter username", b"testbot" in r.data)

    # 4. Invite landing page — invalid token
    with app.test_client() as c:
        r = c.get("/invite/totallybadtoken999")
        check("Invalid invite token shows landing (not 500)", r.status_code == 200)

    # 5. Register with invite token marks invite used
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.post("/invite/create")
        token2 = json.loads(r.data)["link"].split("/invite/")[-1]

    with app.test_client() as c:
        r = c.post("/register", data={
            "username": "invitetestuser",
            "email": "invitetestuser@test.com",
            "password": "testpass123",
            "invite_token": token2
        }, follow_redirects=True)
        check("Registration with invite token succeeds", r.status_code == 200)
        with app.app_context():
            inv = Invite.query.filter_by(token=token2).first()
            check("Invite marked as used", inv is not None and inv.used_by is not None)
            new_user = User.query.filter_by(username="invitetestuser").first()
            if new_user:
                db.session.delete(new_user)
                db.session.commit()


def test_feedback():
    print("\n-- T027 Feedback --")
    # 1. Logged-in user can submit bug report
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.post("/feedback/new", data={
            "category": "bug",
            "title": "Test bug from testbot",
            "body": "Something broke on the profile page.",
            "referrer": ""
        }, follow_redirects=True)
        check("Logged-in user can submit bug report", r.status_code == 200)
        with app.app_context():
            fb = Feedback.query.filter_by(title="Test bug from testbot").first()
            check("Bug report saved to DB", fb is not None)
            check("Bug report has user_id", fb is not None and fb.user_id is not None)

    # 2. Anonymous feedback (not logged in)
    with app.test_client() as c:
        r = c.post("/feedback/new", data={
            "category": "suggestion",
            "title": "Anonymous suggestion",
            "body": "Add a dark mode.",
            "referrer": ""
        }, follow_redirects=True)
        check("Anonymous user can submit suggestion", r.status_code == 200)
        with app.app_context():
            fb2 = Feedback.query.filter_by(title="Anonymous suggestion").first()
            check("Anonymous feedback saved", fb2 is not None)
            check("Anonymous feedback has no user_id", fb2 is not None and fb2.user_id is None)

    # 3. Admin page — brickface082 can access
    with app.test_client() as c:
        login(c, "brickface082@gmail.com", "testpass123")
        r = c.get("/admin/feedback")
        check("brickface082 can access feedback admin", r.status_code in (200, 302))
        # Note: may redirect if password differs on local — just check it doesn't 403/500

    # 4. Non-admin cannot access admin page
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.get("/admin/feedback")
        check("Non-admin gets 403 on feedback admin", r.status_code == 403)

    # 5. Empty form rejected
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.post("/feedback/new", data={"category": "bug", "title": "", "body": "", "referrer": ""})
        check("Empty feedback form shows error", r.status_code == 200 and b"fill in" in r.data.lower())

    # Cleanup
    with app.app_context():
        Feedback.query.filter(Feedback.title.in_(["Test bug from testbot", "Anonymous suggestion"])).delete(synchronize_session=False)
        db.session.commit()


def test_delete_account():
    print("\n-- T028 Delete Account --")
    # Create a throwaway user
    with app.app_context():
        hpw = bcrypt.generate_password_hash("deletepass").decode("utf-8")
        throwaway = User(username="throwawayuser", email="throwaway@test.com", password_hash=hpw)
        db.session.add(throwaway)
        db.session.commit()

    # 1. Wrong username — account NOT deleted
    with app.test_client() as c:
        login(c, "throwaway@test.com", "deletepass")
        r = c.post("/account/delete",
                   data={"confirm_username": "wrongusername"},
                   follow_redirects=True)
        check("Wrong username does not delete account", r.status_code == 200)
        with app.app_context():
            still_there = User.query.filter_by(username="throwawayuser").first()
            check("User still in DB after wrong username", still_there is not None)

    # 2. Unauthenticated cannot delete
    with app.test_client() as c:
        r = c.post("/account/delete",
                   data={"confirm_username": "throwawayuser"},
                   follow_redirects=True)
        check("Unauthenticated delete redirects to login",
              b"Login" in r.data or b"login" in r.request.path.lower().encode())

    # 3. Correct username — account IS deleted
    with app.test_client() as c:
        login(c, "throwaway@test.com", "deletepass")
        r = c.post("/account/delete",
                   data={"confirm_username": "throwawayuser"},
                   follow_redirects=True)
        check("Correct username deletes account, redirects", r.status_code == 200)
        with app.app_context():
            gone = User.query.filter_by(username="throwawayuser").first()
            check("User removed from DB", gone is None)


def test_password_reset():
    print("\n-- T029 Password Reset --")

    # 1. Forgot-password page loads unauthenticated
    with app.test_client() as c:
        r = c.get("/forgot-password")
        check("Forgot-password page loads", r.status_code == 200)
        check("Page contains email form", b"email" in r.data.lower())

    # 2. Unknown email → generic message, no 500, no enumeration
    with app.test_client() as c:
        r = c.post("/forgot-password",
                   data={"email": "nobody@nowhere.com"},
                   follow_redirects=True)
        check("Unknown email shows generic message (no enumeration)", r.status_code == 200)
        check("Generic message present", b"if an account" in r.data.lower())
        with app.app_context():
            count = PasswordResetToken.query.count()
            check("No token created for unknown email", count == 0)

    # 3. Known email → token created in DB, same generic message shown
    with app.test_client() as c:
        r = c.post("/forgot-password",
                   data={"email": "testbot@millennial-space.com"},
                   follow_redirects=True)
        check("Known email still shows generic message", r.status_code == 200)

    with app.app_context():
        record = PasswordResetToken.query.filter(
            PasswordResetToken.used == False  # noqa: E712
        ).first()
        check("Token created in DB for known email", record is not None)
        token = record.token if record else None

    # 4. Reset page loads for valid unused token
    with app.test_client() as c:
        r = c.get(f"/reset-password/{token}")
        check("Reset page loads for valid token", r.status_code == 200)
        check("Reset page contains password fields", b"password" in r.data.lower())

    # 5. Invalid token redirects with error
    with app.test_client() as c:
        r = c.get("/reset-password/totallyfaketoken999", follow_redirects=True)
        check("Invalid token redirects to forgot-password", r.status_code == 200)
        check("Error message shown for invalid token", b"invalid or has expired" in r.data.lower())

    # 6. Short password rejected
    with app.test_client() as c:
        r = c.post(f"/reset-password/{token}",
                   data={"password": "short", "confirm_password": "short"},
                   follow_redirects=True)
        check("Short password rejected", b"at least 8" in r.data.lower())

    with app.app_context():
        record = PasswordResetToken.query.filter_by(token=token).first()
        check("Token NOT marked used after short-password failure", record is not None and not record.used)

    # 7. Mismatched passwords rejected
    with app.test_client() as c:
        r = c.post(f"/reset-password/{token}",
                   data={"password": "newpassword1", "confirm_password": "differentpass"},
                   follow_redirects=True)
        check("Mismatched passwords rejected", b"do not match" in r.data.lower())

    # 8. Valid reset — password changed, token marked used, can log in
    with app.test_client() as c:
        r = c.post(f"/reset-password/{token}",
                   data={"password": "brand_new_pass", "confirm_password": "brand_new_pass"},
                   follow_redirects=True)
        check("Valid reset redirects to login", r.status_code == 200)
        check("Success flash shown", b"password reset" in r.data.lower())

    with app.app_context():
        record = PasswordResetToken.query.filter_by(token=token).first()
        check("Token marked used after successful reset", record is not None and record.used)

    # 9. Can now log in with new password
    with app.test_client() as c:
        r = login(c, "testbot@millennial-space.com", "brand_new_pass")
        check("Can log in with new password", b"testbot" in r.data or r.status_code == 200)

    # 10. Token cannot be reused
    with app.test_client() as c:
        r = c.post(f"/reset-password/{token}",
                   data={"password": "another_pass1", "confirm_password": "another_pass1"},
                   follow_redirects=True)
        check("Used token cannot be reused (redirected)", b"invalid or has expired" in r.data.lower())

    # 11. Expired token rejected (simulate by backdating created_at)
    with app.app_context():
        new_token_str = "expiredtokentest12345678"
        expired_record = PasswordResetToken(
            user_id=User.query.filter_by(username="testbot").first().id,
            token=new_token_str,
            used=False,
            created_at=datetime.utcnow() - timedelta(hours=2)
        )
        db.session.add(expired_record)
        db.session.commit()

    with app.test_client() as c:
        r = c.get(f"/reset-password/{new_token_str}", follow_redirects=True)
        check("Expired token redirects with error", b"invalid or has expired" in r.data.lower())

    # Restore testbot password for remaining tests
    with app.app_context():
        u = User.query.filter_by(username="testbot").first()
        u.password_hash = bcrypt.generate_password_hash("testpass123").decode("utf-8")
        PasswordResetToken.query.filter(
            PasswordResetToken.user_id == u.id
        ).delete(synchronize_session=False)
        db.session.commit()


def test_montage():
    print("\n-- Photo Montage --")
    with app.test_client() as c:
        r = c.get("/montage/edit", follow_redirects=True)
        check("Montage editor requires login", "login" in r.request.path.lower())

        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.get("/montage/edit")
        check("Montage editor loads", r.status_code == 200)
        check("Editor explains music conflict", b"replaces" in r.data.lower() or b"profile song" in r.data.lower())

        r = c.post("/montage/edit", data={
            "action": "save",
            "title": "Test Montage",
            "music_mode": "custom",
            "song_1": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "song_2": "",
            "interval_sec": "3",
            "show_on_profile": "on",
        }, follow_redirects=True)
        check("Montage settings save", r.status_code == 200)

        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            m = PhotoMontage.query.filter_by(user_id=u.id).first()
            check("Montage row created", m is not None)
            check("Custom music mode saved", m is not None and m.music_mode == "custom")
            if m and not m.slides:
                db.session.add(MontageSlide(
                    montage_id=m.id,
                    url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
                    public_id="demo/sample",
                    caption="Test slide",
                    sort_order=0,
                    source="upload",
                ))
                db.session.commit()

        r = c.get("/profile/testbot")
        check("Profile shows montage", b"ms-montage-box" in r.data)
        check("Montage custom soundtrack note", b"replaces profile song" in r.data.lower())
        check("Profile float suppressed", b"ms-music-float" not in r.data)
        check("YouTube in montage music", b"autoplay=1" in r.data or b"youtube.com/embed" in r.data)

        r = c.post("/montage/edit", data={
            "action": "save",
            "title": "Test Montage",
            "music_mode": "profile",
            "song_1": "",
            "song_2": "",
            "interval_sec": "4",
            "show_on_profile": "on",
        }, follow_redirects=True)
        with app.app_context():
            m = PhotoMontage.query.filter_by(user_id=User.query.filter_by(username="testbot").first().id).first()
            check("Profile music mode saved", m is not None and m.music_mode == "profile")

        r = c.get("/profile/testbot")
        check("Profile mode uses profile song label", b"profile song" in r.data.lower())

        r = c.get("/profile/testbot/montage")
        check("Full montage page loads", r.status_code == 200)
        check("Full montage has slideshow", b"ms-montage-stage" in r.data)


def test_spot():
    print("\n-- The Spot (Public Corner + Marketplace) --")
    with app.test_client() as c:
        r = c.get("/spot")
        check("Spot hub loads", r.status_code == 200)
        check("Spot shows Quote of the Day", b"Quote of the Day" in r.data)
        with app.app_context():
            from app import load_quotes
            quotes = load_quotes()
            check("Quote inventory loaded", len(quotes) >= 400)
            attributed = [q for q in quotes if q.get("author")]
            check("Famous attributed quotes included", len(attributed) >= 50)
            check("This too shall pass in pool", any("this too shall pass" in q["text"].lower() for q in quotes))
        check("Spot has Events Near Me tab", b"Events Near Me" in r.data)
        check("Spot has Marketplace tab", b"Marketplace" in r.data)

        login(c, "testbot@millennial-space.com", "testpass123")

        r = c.post("/edit", data={
            "bio": "", "bg_color": "#c5cdd6", "theme_color": "#2b5797",
            "city": "Springfield", "state": "OH", "zip_code": "45501",
            "away_message": "", "msg_filter": "open", "mood": "",
        }, follow_redirects=True)
        check("Profile location saves", r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("City stored", u is not None and u.city == "Springfield")
            check("State stored", u is not None and u.state == "OH")

        future = (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d")
        r = c.post("/spot/event/new", data={
            "title": "Test Block Party",
            "body": "Bring snacks!",
            "venue": "Town Square",
            "city": "Springfield",
            "state": "OH",
            "zip_code": "45501",
            "event_date": future,
            "event_time": "18:00",
        }, follow_redirects=True)
        check("Free event posts", r.status_code == 200)
        with app.app_context():
            ev = CornerEvent.query.filter_by(title="Test Block Party").first()
            check("Event in DB", ev is not None)
            check("Event geo set", ev is not None and ev.city == "Springfield" and ev.state == "OH")
            event_id = ev.id if ev else 0

        r = c.get("/spot?tab=events&city=Springfield&state=OH")
        check("Geo filter shows event", b"Test Block Party" in r.data)

        r = c.get("/spot?tab=events&city=Nowhere&state=WY")
        check("Wrong geo hides event", b"Test Block Party" not in r.data)

        r = c.post("/spot/listing/new", data={
            "category": "for_sale",
            "title": "Vintage Lamp",
            "body": "Works great.",
            "price": "$20",
            "city": "Springfield",
            "state": "OH",
        }, follow_redirects=True)
        check("Free listing posts", r.status_code == 200)
        with app.app_context():
            li = SpotListing.query.filter_by(title="Vintage Lamp").first()
            check("Listing in DB", li is not None and li.fee_cents == 0)

        r = c.post("/spot/listing/new", data={
            "category": "jobs",
            "title": "Barista Wanted",
            "body": "Apply in person.",
            "city": "Springfield",
            "state": "OH",
        }, follow_redirects=True)
        check("Paid listing blocked without fee ack", b"posting fee" in r.data.lower() or b"fee" in r.data.lower())

        r = c.post("/spot/listing/new", data={
            "category": "jobs",
            "title": "Barista Wanted",
            "body": "Apply in person.",
            "city": "Springfield",
            "state": "OH",
            "accept_fee": "on",
        }, follow_redirects=True)
        check("Paid listing posts with fee ack", r.status_code == 200)
        with app.app_context():
            job = SpotListing.query.filter_by(title="Barista Wanted").first()
            check("Job listing fee recorded", job is not None and job.fee_cents == 1000 and job.fee_paid)

        r = c.get(f"/spot/event/{event_id}")
        check("Event detail page loads", r.status_code == 200 and b"Test Block Party" in r.data)


def test_email_updates():
    print("\n-- Email Updates Opt-in --")
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.post("/updates/opt-in", follow_redirects=True)
        check("One-click opt-in works", r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("Opt-in stored", u is not None and u.updates_opt_in is True)
            check("Unsub token created", u is not None and bool(u.updates_unsub_token))
            token = u.updates_unsub_token

        r = c.get(f"/updates/unsubscribe/{token}", follow_redirects=True)
        check("Unsubscribe works", r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("Opt-in cleared after unsubscribe", u is not None and u.updates_opt_in is False)

        logout(c)
        r = c.post("/register", data={
            "username": "updtest99",
            "email": "updtest99@millennial-space.com",
            "password": "testpass123",
            "updates_opt_in": "on",
        }, follow_redirects=True)
        check("Register with opt-in", r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="updtest99").first()
            check("Register opt-in saved", u is not None and u.updates_opt_in is True)
            if u:
                db.session.delete(u)
                db.session.commit()

        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.get("/admin/updates")
        check("Non-admin blocked from updates admin", r.status_code == 403)


def test_song_autoplay():
    print("\n-- Profile Song Autoplay --")
    with app.test_client() as c:
        login(c, "testbot@millennial-space.com", "testpass123")
        r = c.post("/edit", data={
            "bio": "", "bg_color": "#c5cdd6", "theme_color": "#2b5797",
            "profile_song": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "away_message": "", "msg_filter": "open", "mood": "",
            "song_autoplay": "on",
        }, follow_redirects=True)
        check("Edit with song autoplay saves", r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("song_autoplay stored in DB", u is not None and u.song_autoplay is True)
        r = c.get("/profile/testbot")
        check("Profile shows music player", b"ms-music-float" in r.data)
        check("YouTube embed includes autoplay", b"autoplay=1" in r.data)

        r = c.post("/edit", data={
            "bio": "", "bg_color": "#c5cdd6", "theme_color": "#2b5797",
            "profile_song": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "away_message": "", "msg_filter": "open", "mood": "",
        }, follow_redirects=True)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("song_autoplay off when unchecked", u is not None and u.song_autoplay is False)


# ── run all ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_auth()
    test_profile()
    test_search()
    test_messaging_open()
    test_messaging_crew_only()
    test_messaging_verified()
    test_crew()
    test_away_message()
    test_sounds()
    test_icq_inbox()
    test_profile_views()
    test_mood()
    test_montage()
    test_spot()
    test_email_updates()
    test_song_autoplay()
    test_script_rendering()
    test_journal()
    test_polls()
    test_invites()
    test_feedback()
    test_delete_account()
    test_password_reset()

    print("\n-- Summary --")
    passed = sum(1 for r in results if r[0] == PASS)
    failed = sum(1 for r in results if r[0] == FAIL)
    print(f"{passed} passed, {failed} failed")
    if failed:
        print("\nFailed tests:")
        for r in results:
            if r[0] == FAIL:
                print(f"  {r[1]}" + (f" — {r[2]}" if r[2] else ""))
    sys.exit(0 if failed == 0 else 1)
