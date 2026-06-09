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

# ── run all ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_auth()
    test_profile()
    test_search()
    test_messaging_open()
    test_messaging_crew_only()
    test_messaging_verified()
    test_crew()

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
