import os
import sys
import tempfile
import pytest

# Must set DATABASE_URL before app.py is imported by the test module.
# pytest loads conftest.py before collecting/importing test files.
_TEST_DB = os.path.join(tempfile.gettempdir(), "millennial_space_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session", autouse=True)
def seed_database():
    """Create and seed the test SQLite database before any tests run.

    Required layout (tests use hardcoded IDs):
      ID 1 – brickface082   (admin)
      ID 2 – placeholder    (gap filler so testbot lands on ID 3)
      ID 3 – testbot
      ID 4 – testreceiver
    """
    from app import app, db, User, bcrypt

    with app.app_context():
        db.drop_all()
        db.create_all()

        pw = bcrypt.generate_password_hash("testpass123").decode("utf-8")

        users = [
            User(username="brickface082",    email="brickface082@gmail.com",             password_hash=pw),
            User(username="placeholder_ms",  email="placeholder@millennial-space.com",   password_hash=pw),
            User(username="testbot",         email="testbot@millennial-space.com",       password_hash=pw),
            User(username="testreceiver",    email="testreceiver@millennial-space.com",  password_hash=pw),
        ]
        for u in users:
            db.session.add(u)
            db.session.flush()   # assign ID immediately, in insertion order

        db.session.commit()

    yield

    try:
        db.session.remove()
        db.engine.dispose()
    except Exception:
        pass
    if os.path.exists(_TEST_DB):
        try:
            os.remove(_TEST_DB)
        except OSError:
            pass  # Windows may still hold the SQLite lock — harmless
