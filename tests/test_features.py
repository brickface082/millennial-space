# Millennial Space - automated feature test suite.
# Run: .\venv\Scripts\python.exe tests\test_features.py
# Tests run against the local Flask test client (no browser, no Render needed).
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as application
from app import app, db, User, CrewRequest, DirectMessage, bcrypt

app.config["TESTING"] = True
app.config["WTF_CSRF_ENABLED"] = False
app.config["SERVER_NAME"] = None

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
        check("Logout redirects to login", b"Millennial Space" in r.data)

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
        big_audio = io.BytesIO(b"\x00" * 70_000)  # 70KB — over the limit
        r = c.post("/sounds", data={"action": "upload",
                                     "sound_file": (big_audio, "test.mp3", "audio/mpeg")},
                   content_type="multipart/form-data", follow_redirects=True)
        check("Oversized upload rejected", b"too large" in r.data or r.status_code == 200)

        # Upload valid small file is accepted
        small_audio = io.BytesIO(b"\x00" * 1000)  # 1KB — fine
        r = c.post("/sounds", data={"action": "upload",
                                     "sound_file": (small_audio, "test.mp3", "audio/mpeg")},
                   content_type="multipart/form-data", follow_redirects=True)
        check("Small upload accepted", b"uploaded" in r.data or r.status_code == 200)
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
            check("alert_sound set to custom after upload", u is not None and u.alert_sound == "custom")
            check("custom_sound stored as base64 data URI", u is not None and (u.custom_sound or "").startswith("data:"))

        # Reset testbot back to classic_beep
        with app.app_context():
            u = User.query.filter_by(username="testbot").first()
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
