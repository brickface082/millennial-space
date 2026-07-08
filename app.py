import os
import re
import secrets
from urllib.parse import quote as url_quote
from io import BytesIO
from PIL import Image
from datetime import datetime
import random
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, current_user, logout_user, login_required
import cloudinary
import cloudinary.uploader
from flask_mail import Mail, Message
from datetime import timedelta
from dotenv import load_dotenv
from markupsafe import Markup, escape
load_dotenv()

BBCODE_PATTERNS = [
    (re.compile(r"\[b\](.*?)\[/b\]", re.I | re.S), r"<strong>\1</strong>"),
    (re.compile(r"\[i\](.*?)\[/i\]", re.I | re.S), r"<em>\1</em>"),
    (re.compile(r"\[glitter\](.*?)\[/glitter\]", re.I | re.S), r'<span class="ms-glitter">\1</span>'),
]
BULLETIN_MAX_LEN = 500
PROFILE_VIEWERS_LIMIT = 10
CREW_PREVIEW_COUNT = 5


def format_bbcode(text):
    if not text:
        return Markup("")
    s = str(escape(text))
    for pattern, repl in BBCODE_PATTERNS:
        s = pattern.sub(repl, s)
    return Markup(s.replace("\n", "<br>\n"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
basedir = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(basedir, "instance", "site.db"))
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["UPLOAD_FOLDER"] = os.path.join(basedir, "static/uploads")
app.config["PREFERRED_URL_SCHEME"] = "https"

app.config["MAIL_SERVER"]   = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"]     = int(os.environ.get("MAIL_PORT", "587"))
app.config["MAIL_USE_TLS"]  = True
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_USERNAME", "noreply@millennial-space.com")

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


@app.template_filter("bbcode")
def bbcode_filter(text):
    return format_bbcode(text)


SITE_DEFAULTS = {
    "bg_color": "#c5cdd6",
    "theme_color": "#2b5797",
    "font_choice": "Arial",
    "dark_mode": False,
}
SITE_BRAND = "OurMillennialSpace"
SITE_NAME = "Our Millennial Space"

def _ensure_cloudinary():
    """Apply Cloudinary credentials before each upload."""
    url = os.environ.get("CLOUDINARY_URL", "")
    match = re.match(r"cloudinary://([^:]+):([^@]+)@([^/]+)", url)
    if match:
        cloudinary.config(
            api_key=match.group(1),
            api_secret=match.group(2),
            cloud_name=match.group(3),
        )

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def utility_processor():
    """image_url(value, folder) — returns the correct URL for a stored image.
    Handles both legacy local filenames and new Cloudinary URLs (T005/SOP T001)."""
    def image_url(value, folder):
        if not value or value == 'default.jpg':
            return None
        if value.startswith('http'):
            return value  # Cloudinary URL — use directly
        return url_for('static', filename=f'uploads/{folder}/{value}')  # legacy local

    def song_url(value):
        """Legacy local MP3 filename → static URL."""
        if not value:
            return None
        if value.startswith('http'):
            return value
        return url_for('static', filename=f'uploads/profile_songs/{value}')

    def user_music_items(user):
        return get_user_music_items(user)

    def quote_sound_url(key):
        if key in MOVIE_QUOTE_PACK:
            wav = os.path.join(basedir, "static", "sounds", "quotes", f"{key}.wav")
            ext = "wav" if os.path.isfile(wav) else "mp3"
            return url_for("static", filename=f"sounds/quotes/{key}.{ext}")
        return None

    def user_alert_sounds(user):
        if not user or not getattr(user, "is_authenticated", False) or not user.is_authenticated:
            return {}
        return {user_sound_key(s.id): s.audio_data for s in user.sound_library}

    return dict(
        image_url=image_url,
        song_url=song_url,
        user_music_items=user_music_items,
        music_provider_labels=MUSIC_PROVIDER_LABELS,
        movie_quote_pack=MOVIE_QUOTE_PACK,
        quote_sound_url=quote_sound_url,
        user_alert_sounds=user_alert_sounds,
        site_defaults=SITE_DEFAULTS,
        site_brand=SITE_BRAND,
        site_name=SITE_NAME,
        format_fee=format_fee,
        quote_of_the_day=quote_of_the_day,
    )

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(60), nullable=False)
    bio = db.Column(db.Text, default="")
    profile_pic = db.Column(db.String(120), default="default.jpg")
    bg_color = db.Column(db.String(20), default="#c5cdd6")
    bg_image = db.Column(db.String(120), default="")
    youtube_url = db.Column(db.String(200), default="")
    spotify_url = db.Column(db.String(200), default="")
    top8 = db.Column(db.String(200), default="")
    status = db.Column(db.String(10), default="online")
    last_seen = db.Column(db.DateTime, nullable=True)
    msg_filter = db.Column(db.String(10), default="open")
    away_message = db.Column(db.Text, default="")
    alert_sound = db.Column(db.String(30), default="classic_beep")
    custom_sound = db.Column(db.Text, default="")
    profile_views = db.Column(db.Integer, default=0)
    mood = db.Column(db.String(30), default="")
    polls_enabled = db.Column(db.Boolean, default=False)
    theme_color = db.Column(db.String(7), default="#2b5797")
    dark_mode = db.Column(db.Boolean, default=False)
    font_choice = db.Column(db.String(50), default="Arial")
    ideal_meet = db.Column(db.Text, default="")
    city = db.Column(db.String(80), default="")
    state = db.Column(db.String(2), default="")
    zip_code = db.Column(db.String(10), default="")
    joined_at = db.Column(db.DateTime, nullable=True)
    profile_song = db.Column(db.Text, default="")
    song_autoplay = db.Column(db.Boolean, default=False)
    profile_theme = db.Column(db.String(30), default="")
    custom_css = db.Column(db.Text, default="")
    updates_opt_in = db.Column(db.Boolean, default=False)
    updates_opt_in_at = db.Column(db.DateTime, nullable=True)
    updates_unsub_token = db.Column(db.String(64), unique=True, nullable=True)
    show_daily_quote = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"User({self.username})"


class ProfileView(db.Model):
    """Who viewed whose profile — MySpace vanity metric."""
    __tablename__ = "profile_view"
    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    viewer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    viewed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    profile_user = db.relationship("User", foreign_keys=[profile_id],
                                   backref=db.backref("profile_view_log", lazy="dynamic"))
    viewer = db.relationship("User", foreign_keys=[viewer_id])


class UserSound(db.Model):
    """User-owned alert clips — record, import, or Kokoro TTS."""
    __tablename__ = "user_sound"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    label = db.Column(db.String(60), nullable=False, default="My Sound")
    audio_data = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(10), default="upload")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship("User", backref=db.backref("sound_library", lazy="dynamic",
                             order_by="UserSound.created_at.desc()"))


class CrewRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    to_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending, accepted, blocked
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    from_user = db.relationship("User", foreign_keys=[from_id], backref=db.backref("sent_requests", lazy=True))
    to_user = db.relationship("User", foreign_keys=[to_id], backref=db.backref("received_requests", lazy=True))

class Bulletin(db.Model):
    """Short status updates — MySpace bulletin board, separate from long blurbs."""
    __tablename__ = "bulletin"
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref=db.backref("bulletins", lazy=True,
                             order_by="Bulletin.timestamp.desc()"))

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(120), default="")
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref=db.backref("posts", lazy=True, order_by="Post.timestamp.desc()"))

    def __repr__(self):
        return f"Post({self.id}, {self.user_id})"

class DirectMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    to_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    sender = db.relationship("User", foreign_keys=[from_id], backref=db.backref("sent_messages", lazy=True))
    recipient = db.relationship("User", foreign_keys=[to_id], backref=db.backref("received_messages", lazy=True))

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    profile_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    author = db.relationship("User", foreign_keys=[author_id], backref=db.backref("comments_made", lazy=True))
    profile_user = db.relationship("User", foreign_keys=[profile_id], backref=db.backref("comments_received", lazy=True))

class JournalEntry(db.Model):
    """T023 — private diary entries and public blog posts.
    entry_type is 'diary' (owner-only) or 'blog' (public).
    entry_type is immutable after creation — never expose an edit UI for it."""
    __tablename__ = "journal_entry"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    entry_type = db.Column(db.String(10), nullable=False)  # 'diary' | 'blog'
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    author = db.relationship("User", backref=db.backref("journal_entries", lazy=True))
    photos = db.relationship("EntryPhoto", backref="entry", lazy=True,
                             cascade="all, delete-orphan",
                             order_by="EntryPhoto.position.asc()")

class EntryPhoto(db.Model):
    """Photos attached to a JournalEntry. Stored in Cloudinary."""
    __tablename__ = "entry_photo"
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=False)
    url = db.Column(db.Text, nullable=False)
    public_id = db.Column(db.String(300), nullable=False)
    caption = db.Column(db.String(300), default="")
    position = db.Column(db.Integer, default=0)

class Poll(db.Model):
    """T024 — site-wide polls. Visible based on creator's audience + voter's filter."""
    __tablename__ = "poll"
    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    question = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    creator = db.relationship("User", backref=db.backref("polls_created", lazy=True))
    options = db.relationship("PollOption", backref="poll", lazy=True,
                              cascade="all, delete-orphan",
                              order_by="PollOption.position.asc()")
    votes = db.relationship("PollVote", backref="poll", lazy=True,
                            cascade="all, delete-orphan")

class PollOption(db.Model):
    __tablename__ = "poll_option"
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("poll.id"), nullable=False)
    text = db.Column(db.String(200), nullable=False)
    position = db.Column(db.Integer, default=0)

class PollVote(db.Model):
    __tablename__ = "poll_vote"
    __table_args__ = (db.UniqueConstraint("poll_id", "user_id", name="uq_poll_user"),)
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("poll.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey("poll_option.id"), nullable=False)
    voted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    voter = db.relationship("User", backref=db.backref("poll_votes", lazy=True))
    chosen = db.relationship("PollOption", backref=db.backref("vote_records", lazy=True))

class PhotoAlbum(db.Model):
    __tablename__ = "photo_album"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    photos = db.relationship("Photo", backref="album", lazy=True, cascade="all, delete-orphan",
                             order_by="Photo.created_at.asc()")
    owner = db.relationship("User", backref=db.backref("albums", lazy=True))

class Photo(db.Model):
    __tablename__ = "photo"
    id = db.Column(db.Integer, primary_key=True)
    album_id = db.Column(db.Integer, db.ForeignKey("photo_album.id"), nullable=False)
    url = db.Column(db.Text, nullable=False)          # Cloudinary secure URL
    public_id = db.Column(db.String(200), nullable=False)  # Cloudinary public_id for deletion
    caption = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class PhotoMontage(db.Model):
    """Slideshow montage on profile — optional custom soundtrack."""
    __tablename__ = "photo_montage"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    title = db.Column(db.String(100), default="My Montage")
    music_mode = db.Column(db.String(10), default="profile")  # profile | custom
    song_1 = db.Column(db.Text, default="")
    song_2 = db.Column(db.Text, default="")
    interval_sec = db.Column(db.Integer, default=4)
    show_on_profile = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    owner = db.relationship("User", backref=db.backref("montage", uselist=False, lazy=True))
    slides = db.relationship(
        "MontageSlide", backref="montage", lazy=True, cascade="all, delete-orphan",
        order_by="MontageSlide.sort_order.asc()",
    )


class MontageSlide(db.Model):
    __tablename__ = "montage_slide"
    id = db.Column(db.Integer, primary_key=True)
    montage_id = db.Column(db.Integer, db.ForeignKey("photo_montage.id"), nullable=False)
    url = db.Column(db.Text, nullable=False)
    public_id = db.Column(db.String(200), default="")
    caption = db.Column(db.String(200), default="")
    sort_order = db.Column(db.Integer, default=0)
    source = db.Column(db.String(10), default="upload")  # upload | album
    source_photo_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class SpotListing(db.Model):
    """Craigslist-style marketplace listing — paid categories only."""
    __tablename__ = "spot_listing"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    price = db.Column(db.String(40), default="")
    city = db.Column(db.String(80), default="")
    state = db.Column(db.String(2), default="")
    zip_code = db.Column(db.String(10), default="")
    fee_cents = db.Column(db.Integer, default=0)
    fee_paid = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(10), default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    poster = db.relationship("User", backref=db.backref("spot_listings", lazy=True,
                             order_by="SpotListing.created_at.desc()"))


class CornerEvent(db.Model):
    """Public Corner — geographically scoped local happenings."""
    __tablename__ = "corner_event"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    venue = db.Column(db.String(120), default="")
    city = db.Column(db.String(80), default="")
    state = db.Column(db.String(2), default="")
    zip_code = db.Column(db.String(10), default="")
    event_at = db.Column(db.DateTime, nullable=False)
    is_promoted = db.Column(db.Boolean, default=False)
    fee_cents = db.Column(db.Integer, default=0)
    fee_paid = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(10), default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    poster = db.relationship("User", backref=db.backref("corner_events", lazy=True,
                             order_by="CornerEvent.event_at.asc()"))


class Invite(db.Model):
    """T026 — reusable invite links. Each user gets one permanent link; unlimited signups."""
    __tablename__ = "invite"
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    used_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # legacy; unused
    used_at = db.Column(db.DateTime, nullable=True)  # legacy; unused
    creator = db.relationship("User", foreign_keys=[created_by],
                              backref=db.backref("invites_sent", lazy=True))
    used_by_user = db.relationship("User", foreign_keys=[used_by],
                                   backref=db.backref("invite_used", uselist=False, lazy=True))


class InviteReferral(db.Model):
    """Signup attributed to an invite link (link stays reusable)."""
    __tablename__ = "invite_referral"
    id = db.Column(db.Integer, primary_key=True)
    invite_id = db.Column(db.Integer, db.ForeignKey("invite.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    referred_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    invite = db.relationship("Invite", backref=db.backref("referrals", lazy=True))
    user = db.relationship("User", backref=db.backref("referred_via", uselist=False, lazy=True))

class Feedback(db.Model):
    """T027 — bug reports and suggestions. user_id is nullable so anonymous submissions work."""
    __tablename__ = "feedback"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    category = db.Column(db.String(20), nullable=False)   # 'bug' | 'suggestion'
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open")  # 'open' | 'reviewed'
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    submitter = db.relationship("User", backref=db.backref("feedback_submitted", lazy=True))

class PasswordResetToken(db.Model):
    """T029 — single-use, 1-hour password reset tokens. FMEA: mark used before any response."""
    __tablename__ = "password_reset_token"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    used = db.Column(db.Boolean, nullable=False, default=False)
    user = db.relationship("User", backref=db.backref("reset_tokens", lazy=True))

COMMENTS_PER_PAGE = 10
UPDATES_PER_PAGE = 10
PROFILE_PREVIEW_COUNT = 3

LISTING_LIFESPAN_DAYS = 30
EVENT_LIFESPAN_DAYS = 60
EVENT_PROMOTE_FEE_CENTS = 500

MARKETPLACE_CATEGORIES = {
    "for_sale": {"label": "For Sale — By Owner", "fee_cents": 0},
    "wanted": {"label": "Wanted", "fee_cents": 0},
    "housing": {"label": "Housing / Apartments", "fee_cents": 500},
    "jobs": {"label": "Jobs", "fee_cents": 1000},
    "gigs": {"label": "Gigs", "fee_cents": 300},
    "services": {"label": "Services", "fee_cents": 500},
}

US_STATES = [
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("DC", "District of Columbia"), ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"),
    ("ID", "Idaho"), ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"),
    ("KS", "Kansas"), ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"),
    ("MD", "Maryland"), ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"),
    ("MS", "Mississippi"), ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"),
    ("NV", "Nevada"), ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"),
    ("NY", "New York"), ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"),
    ("OK", "Oklahoma"), ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"),
    ("SC", "South Carolina"), ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"),
    ("UT", "Utah"), ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"),
    ("WV", "West Virginia"), ("WI", "Wisconsin"), ("WY", "Wyoming"),
]
VALID_STATE_CODES = {code for code, _ in US_STATES}

PROFILE_THEME_PRESETS = {
    "classic_slate": {
        "label": "Classic Slate (default)",
        "bg_color": SITE_DEFAULTS["bg_color"],
        "theme_color": SITE_DEFAULTS["theme_color"],
        "font_choice": SITE_DEFAULTS["font_choice"],
        "dark_mode": SITE_DEFAULTS["dark_mode"],
    },
    "classic_pink": {
        "label": "Classic Pink",
        "bg_color": "#ff66b2",
        "theme_color": "#cc44aa",
        "font_choice": "Arial",
        "dark_mode": False,
    },
    "emo_black": {
        "label": "Emo Black",
        "bg_color": "#111111",
        "theme_color": "#990000",
        "font_choice": "Courier New",
        "dark_mode": True,
    },
    "glitter_goth": {
        "label": "Glitter Goth",
        "bg_color": "#1a001a",
        "theme_color": "#ff00ff",
        "font_choice": "Georgia",
        "dark_mode": True,
    },
    "ocean_blue": {
        "label": "Ocean Blue",
        "bg_color": "#003366",
        "theme_color": "#0099cc",
        "font_choice": "Verdana",
        "dark_mode": False,
    },
    "scene_kid": {
        "label": "Scene Kid",
        "bg_color": "#ff0099",
        "theme_color": "#00ffcc",
        "font_choice": "Trebuchet MS",
        "dark_mode": False,
    },
    "retro_green": {
        "label": "Retro Green",
        "bg_color": "#003300",
        "theme_color": "#66ff66",
        "font_choice": "Courier New",
        "dark_mode": True,
    },
    "sunset": {
        "label": "Sunset Orange",
        "bg_color": "#ff6600",
        "theme_color": "#cc0066",
        "font_choice": "Georgia",
        "dark_mode": False,
    },
    "neon_nights": {
        "label": "Neon Nights",
        "bg_color": "#0a0a1a",
        "theme_color": "#00ffff",
        "font_choice": "Arial",
        "dark_mode": True,
    },
}

_CSS_BLOCKED_PATTERNS = [
    re.compile(r"javascript\s*:", re.I),
    re.compile(r"expression\s*\(", re.I),
    re.compile(r"@import\b", re.I),
    re.compile(r"behavior\s*:", re.I),
    re.compile(r"binding\s*:", re.I),
    re.compile(r"<\s*/?\s*script", re.I),
    re.compile(r"<\s*/?\s*iframe", re.I),
    re.compile(r"url\s*\(\s*['\"]?\s*data:", re.I),
]

def sanitize_profile_css(css):
    """Whitelist-style CSS sanitizer for MySpace-style profile themes."""
    if not css:
        return ""
    css = css.strip()[:8000]
    for pat in _CSS_BLOCKED_PATTERNS:
        if pat.search(css):
            return ""
    return css

def _paginate_query(query, page, per_page):
    total = query.count()
    if page < 1:
        page = 1
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return items, page, total_pages, total

def format_last_seen(dt):
    """Human-readable last activity for profile sidebar."""
    if not dt:
        return None
    delta = datetime.utcnow() - dt
    secs = delta.total_seconds()
    if secs < 120:
        return "just now"
    if secs < 3600:
        mins = int(secs // 60)
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    if secs < 86400:
        hrs = int(secs // 3600)
        return f"{hrs} hour{'s' if hrs != 1 else ''} ago"
    if secs < 604800:
        days = int(secs // 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    return dt.strftime("%b %d, %Y")

def extract_url(value):
    value = value.strip()
    match = re.search(r'src=["\']([^"\']+)["\']', value)
    if match:
        return match.group(1)
    return value

MUSIC_PROVIDER_LABELS = {
    "youtube": "YouTube",
    "spotify": "Spotify",
    "soundcloud": "SoundCloud",
    "pandora": "Pandora",
    "apple": "Apple Music",
    "bandcamp": "Bandcamp",
    "link": "this link",
}

def parse_media_embed(url, autoplay=False):
    """Parse a share or embed URL into player metadata for the profile music box."""
    if not url:
        return None
    url = url.strip()
    if not url.startswith("http") and url.endswith(".mp3"):
        return {"kind": "audio", "embed_url": None, "link_url": None, "height": 32, "raw": url}
    src_match = re.search(r'src=["\']([^"\']+)["\']', url)
    if src_match:
        url = src_match.group(1).strip()
    yt_match = re.search(
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|music\.youtube\.com/watch\?v=|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
        url,
    )
    if yt_match:
        vid = yt_match.group(1)
        embed = f"https://www.youtube.com/embed/{vid}"
        if autoplay:
            embed += "?autoplay=1&mute=1"
        return {
            "kind": "youtube",
            "embed_url": embed,
            "link_url": f"https://www.youtube.com/watch?v={vid}",
            "height": 200,
            "raw": url,
            "autoplay": autoplay,
        }
    sp_match = re.search(
        r'open\.spotify\.com/(?:embed/)?(track|album|playlist|episode|show)/([a-zA-Z0-9]+)',
        url,
    )
    if sp_match:
        stype, sid = sp_match.group(1), sp_match.group(2)
        return {
            "kind": "spotify",
            "embed_url": f"https://open.spotify.com/embed/{stype}/{sid}",
            "link_url": f"https://open.spotify.com/{stype}/{sid}",
            "height": 152 if stype in ("track", "episode") else 352,
            "raw": url,
        }
    sc_match = re.search(r'soundcloud\.com/([^/?#]+/[^/?#]+)', url)
    if sc_match:
        link = f"https://soundcloud.com/{sc_match.group(1)}"
        auto_flag = "true" if autoplay else "false"
        embed = (
            "https://w.soundcloud.com/player/?"
            f"url={url_quote(link, safe='')}&color=%23ff66b2&auto_play={auto_flag}"
            "&hide_related=false&show_comments=true&show_user=true"
            "&show_reposts=false&show_teaser=true"
        )
        return {"kind": "soundcloud", "embed_url": embed, "link_url": link, "height": 166, "raw": url, "autoplay": autoplay}
    if "pandora.com" in url:
        return {"kind": "pandora", "embed_url": None, "link_url": url, "height": 0, "raw": url}
    if "music.apple.com" in url:
        embed = url.replace("https://music.apple.com", "https://embed.music.apple.com", 1)
        if "embed.music.apple.com" not in embed:
            embed = None
        return {
            "kind": "apple",
            "embed_url": embed,
            "link_url": url,
            "height": 175,
            "raw": url,
        }
    if "bandcamp.com" in url:
        return {"kind": "bandcamp", "embed_url": None, "link_url": url, "height": 0, "raw": url}
    if url.startswith("http"):
        return {"kind": "link", "embed_url": None, "link_url": url, "height": 0, "raw": url}
    return None

def get_user_music_items(user):
    """Collect embeddable music entries for a profile (primary link + legacy fields)."""
    items = []
    ap = bool(getattr(user, "song_autoplay", False))
    if user.profile_song:
        item = parse_media_embed(user.profile_song, autoplay=ap)
        if item:
            items.append(item)
    else:
        for legacy in (user.youtube_url, user.spotify_url):
            if legacy:
                item = parse_media_embed(legacy, autoplay=ap)
                if item:
                    items.append(item)
    return items


def get_or_create_montage(user):
    m = PhotoMontage.query.filter_by(user_id=user.id).first()
    if not m:
        m = PhotoMontage(user_id=user.id)
        db.session.add(m)
        db.session.commit()
    return m


def get_montage_music_items(montage, user):
    """Songs for montage playback — custom URLs or profile song."""
    ap = bool(getattr(user, "song_autoplay", False))
    if montage.music_mode == "custom":
        items = []
        for raw in (montage.song_1, montage.song_2):
            url = extract_url((raw or "").strip())
            if url:
                item = parse_media_embed(url, autoplay=ap)
                if item:
                    items.append(item)
        return items
    return get_user_music_items(user)


def montage_display_state(montage, user):
    """Return slideshow visibility + music bundled in montage vs separate profile player."""
    if not montage or not montage.slides or not montage.show_on_profile:
        return False, [], "none", False
    uses_custom = montage.music_mode == "custom" and bool(
        (montage.song_1 or "").strip() or (montage.song_2 or "").strip()
    )
    items = get_montage_music_items(montage, user) if uses_custom else (
        get_user_music_items(user) if montage.music_mode == "profile" else []
    )
    if uses_custom and not items:
        items = get_user_music_items(user)
        label = "fallback"
    elif uses_custom:
        label = "custom"
    elif montage.music_mode == "profile" and items:
        label = "profile"
    else:
        label = "none"
    suppress_float = bool(items) and label in ("custom", "profile", "fallback")
    return True, items, label, suppress_float


def spot_payments_live():
    return os.environ.get("SPOT_PAYMENTS_LIVE", "").lower() in ("1", "true", "yes")


def format_fee(cents):
    if not cents:
        return "Free"
    return f"${cents / 100:.2f}"


def listing_fee_cents(category):
    info = MARKETPLACE_CATEGORIES.get(category, {})
    return info.get("fee_cents", 0)


_quotes_cache = None
_quotes_mtime = None


def load_quotes():
    global _quotes_cache, _quotes_mtime
    import json

    paths = [
        os.path.join(basedir, "data", "quotes.json"),
        os.path.join(basedir, "data", "famous_quotes.json"),
    ]
    try:
        mtime = max(os.path.getmtime(p) for p in paths if os.path.isfile(p))
    except (OSError, ValueError):
        mtime = None
    if _quotes_cache is not None and mtime == _quotes_mtime:
        return _quotes_cache

    merged = []
    seen = set()
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for item in data:
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append({
                    "text": text,
                    "author": (item.get("author") or "").strip(),
                    "source": item.get("source", ""),
                })
        except (OSError, ValueError):
            continue
    _quotes_cache = merged
    _quotes_mtime = mtime
    return _quotes_cache


def quote_of_the_day():
    quotes = load_quotes()
    if not quotes:
        return None
    day_num = int(datetime.utcnow().strftime("%Y%m%d"))
    return quotes[day_num % len(quotes)]


def normalize_state(state):
    code = (state or "").strip().upper()[:2]
    return code if code in VALID_STATE_CODES else ""


def parse_location_fields(city, state, zip_code):
    return (
        (city or "").strip()[:80],
        normalize_state(state),
        (zip_code or "").strip()[:10],
    )


def user_location_label(user):
    if not user:
        return ""
    parts = []
    if user.city:
        parts.append(user.city)
    if user.state:
        parts.append(user.state)
    return ", ".join(parts)


def spot_location_from_request():
    city = request.args.get("city", request.form.get("city", "")).strip()
    state = normalize_state(request.args.get("state", request.form.get("state", "")))
    zip_code = request.args.get("zip_code", request.form.get("zip_code", "")).strip()[:10]
    if current_user.is_authenticated and not city and not state:
        city, state, zip_code = current_user.city, current_user.state, current_user.zip_code
    return parse_location_fields(city, state, zip_code)


def apply_location_filter(query, model, city, state):
    if city and state:
        return query.filter(
            db.func.lower(model.city) == city.lower(),
            model.state == state,
        )
    if state:
        return query.filter(model.state == state)
    return query


def confirm_spot_fee(fee_cents, form):
    if fee_cents <= 0:
        return True, False
    if spot_payments_live():
        return form.get("accept_fee") == "on", False
    return form.get("accept_fee") == "on", True


def parse_event_datetime(date_str, time_str):
    date_str = (date_str or "").strip()
    time_str = (time_str or "12:00").strip()
    if not date_str:
        return None
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def ensure_updates_unsub_token(user):
    if not user.updates_unsub_token:
        user.updates_unsub_token = secrets.token_urlsafe(32)


def set_updates_opt_in(user, opted_in):
    user.updates_opt_in = bool(opted_in)
    if user.updates_opt_in:
        ensure_updates_unsub_token(user)
        if not user.updates_opt_in_at:
            user.updates_opt_in_at = datetime.utcnow()
    else:
        user.updates_opt_in_at = None


def updates_unsubscribe_url(user):
    ensure_updates_unsub_token(user)
    return url_for("updates_unsubscribe", token=user.updates_unsub_token, _external=True)


def send_update_email(user, subject, body):
    """Send a site update email with unsubscribe footer."""
    ensure_updates_unsub_token(user)
    unsub = updates_unsubscribe_url(user)
    full_body = (
        f"Hi {user.username},\n\n"
        f"{body.strip()}\n\n"
        f"---\n"
        f"You're receiving this because you opted in to {SITE_NAME} updates.\n"
        f"Unsubscribe: {unsub}\n"
    )
    msg = Message(subject, recipients=[user.email], body=full_body)
    mail.send(msg)


def spot_redirect_params(city, state, zip_code, tab="events", category=""):
    params = {"tab": tab}
    if city:
        params["city"] = city
    if state:
        params["state"] = state
    if zip_code:
        params["zip_code"] = zip_code
    if category:
        params["category"] = category
    return params


MONTAGE_MAX_SLIDES = 30

def profile_music_link_value(user):
    """Prefill edit form — primary song URL or first legacy music field."""
    return user.profile_song or user.youtube_url or user.spotify_url or ""

def _is_local_profile_song(stored):
    return bool(stored) and not stored.startswith("http") and stored.endswith(".mp3")

def upload_to_cloudinary(file_obj, folder, resize=None):
    """Upload a file to Cloudinary. Returns (secure_url, public_id).
    resize: optional (w, h) tuple — thumbnail before upload (used for profile pics)."""
    _ensure_cloudinary()
    if resize:
        img = Image.open(file_obj)
        img.thumbnail(resize)
        buf = BytesIO()
        img.save(buf, format=(img.format or 'JPEG'))
        buf.seek(0)
        file_obj = buf
    result = cloudinary.uploader.upload(
        file_obj,
        folder=f"millennial-space/{folder}",
        resource_type="image"
    )
    return result['secure_url'], result['public_id']

def _profile_songs_dir():
    path = os.path.join(basedir, "static", "uploads", "profile_songs")
    os.makedirs(path, exist_ok=True)
    return path

def delete_profile_song_file(stored):
    """Remove a legacy locally stored MP3 (ignores embed URLs)."""
    if not _is_local_profile_song(stored):
        return
    path = os.path.join(_profile_songs_dir(), stored)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass

@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    # T026 — accept invite token from query param or form hidden field
    invite_token = request.args.get("invite", "").strip()
    invite = Invite.query.filter_by(token=invite_token).first() if invite_token else None
    invited_by = invite.creator.username if invite else None
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        token = request.form.get("invite_token", "").strip()
        hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
        user = User(username=username, email=email, password_hash=hashed_pw,
                    joined_at=datetime.utcnow())
        if request.form.get("updates_opt_in") == "on":
            set_updates_opt_in(user, True)
        db.session.add(user)
        db.session.flush()  # get user.id before commit
        if token:
            inv = Invite.query.filter_by(token=token).first()
            if inv:
                db.session.add(InviteReferral(invite_id=inv.id, user_id=user.id))
        db.session.commit()
        flash("Account created! You can now log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", invited_by=invited_by, invite_token=invite_token)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Welcome back!", "success")
            return redirect(url_for("profile", username=user.username))
        else:
            flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/profile/<username>")
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    # Increment view counter — owner views don't count (W002 paper think: unauthenticated counts per spec)
    is_owner = current_user.is_authenticated and current_user.id == user.id
    if not is_owner:
        try:
            user.profile_views = (user.profile_views or 0) + 1
            viewer_id = current_user.id if current_user.is_authenticated else None
            db.session.add(ProfileView(profile_id=user.id, viewer_id=viewer_id))
            db.session.commit()
        except Exception:
            db.session.rollback()
    posts_query = Post.query.filter_by(user_id=user.id).order_by(Post.timestamp.desc())
    total_posts = posts_query.count()
    posts = posts_query.limit(PROFILE_PREVIEW_COUNT).all()
    posts_has_more = total_posts > PROFILE_PREVIEW_COUNT

    comments_query = Comment.query.filter_by(profile_id=user.id).order_by(Comment.timestamp.desc())
    total_comments = comments_query.count()
    comments = comments_query.limit(PROFILE_PREVIEW_COUNT).all()
    comments_has_more = total_comments > PROFILE_PREVIEW_COUNT
    crew_status = None
    crew_request_id = None
    if current_user.is_authenticated and current_user.id != user.id:
        req = get_crew_status(current_user.id, user.id)
        if req:
            crew_status = req.status
            crew_request_id = req.id
    top8_users = []
    if user.top8:
        for uid in user.top8.split(","):
            if uid:
                m = User.query.get(int(uid))
                if m:
                    top8_users.append(m)
    mood_labels = {key: label for key, label in MOOD_OPTIONS if key}
    # T022: recent photos strip — 4 most recent photos across all albums
    recent_photos = (Photo.query.join(PhotoAlbum)
                     .filter(PhotoAlbum.user_id == user.id)
                     .order_by(Photo.created_at.desc())
                     .limit(4).all())
    album_count = PhotoAlbum.query.filter_by(user_id=user.id).count()
    crew_list = get_user_crew(user.id)
    bulletins_query = Bulletin.query.filter_by(user_id=user.id).order_by(Bulletin.timestamp.desc())
    total_bulletins = bulletins_query.count()
    bulletins = bulletins_query.limit(PROFILE_PREVIEW_COUNT).all()
    bulletins_has_more = total_bulletins > PROFILE_PREVIEW_COUNT
    mutual_crew_count = 0
    if current_user.is_authenticated and not is_owner:
        mutual_crew_count = get_mutual_crew_count(current_user.id, user.id)
    profile_url = url_for("profile", username=user.username, _external=True)
    member_since = user.joined_at.strftime("%b %Y") if user.joined_at else None
    recent_viewers = []
    if is_owner:
        seen = set()
        for pv in (ProfileView.query.filter_by(profile_id=user.id)
                   .order_by(ProfileView.viewed_at.desc())
                   .limit(50).all()):
            key = pv.viewer_id or 0
            if key in seen:
                continue
            seen.add(key)
            recent_viewers.append(pv)
            if len(recent_viewers) >= PROFILE_VIEWERS_LIMIT:
                break
    montage = PhotoMontage.query.filter_by(user_id=user.id).first()
    show_montage, montage_music_items, montage_music_label, suppress_profile_music = (
        montage_display_state(montage, user)
    )
    return render_template(
        "profile.html",
        user=user,
        recent_viewers=recent_viewers,
        crew_preview_count=CREW_PREVIEW_COUNT,
        posts=posts,
        comments=comments,
        crew_status=crew_status,
        crew_request_id=crew_request_id,
        top8_users=top8_users,
        crew_list=crew_list,
        is_owner=is_owner,
        mood_labels=mood_labels,
        mood_options=MOOD_OPTIONS,
        recent_photos=recent_photos,
        album_count=album_count,
        total_comments=total_comments,
        comments_has_more=comments_has_more,
        total_posts=total_posts,
        posts_has_more=posts_has_more,
        total_bulletins=total_bulletins,
        bulletins_has_more=bulletins_has_more,
        last_seen_label=format_last_seen(user.last_seen),
        bulletins=bulletins,
        mutual_crew_count=mutual_crew_count,
        profile_url=profile_url,
        member_since=member_since,
        montage=montage if show_montage else None,
        montage_music_items=montage_music_items,
        montage_music_label=montage_music_label,
        daily_quote=quote_of_the_day() if user.show_daily_quote else None,
        suppress_profile_music=suppress_profile_music,
        profile_music_link=profile_music_link_value(user),
    )

@app.route("/profile/<username>/comments")
def profile_comments(username):
    user = User.query.filter_by(username=username).first_or_404()
    is_owner = current_user.is_authenticated and current_user.id == user.id
    page = request.args.get("page", 1, type=int)
    comments_query = Comment.query.filter_by(profile_id=user.id).order_by(Comment.timestamp.desc())
    comments, page, total_pages, total_comments = _paginate_query(
        comments_query, page, COMMENTS_PER_PAGE
    )
    return render_template(
        "profile_comments.html",
        user=user,
        comments=comments,
        is_owner=is_owner,
        page=page,
        total_pages=total_pages,
        total_comments=total_comments,
    )

@app.route("/profile/<username>/updates")
def profile_updates(username):
    user = User.query.filter_by(username=username).first_or_404()
    is_owner = current_user.is_authenticated and current_user.id == user.id
    tab = request.args.get("tab", "bulletins")
    if tab not in ("bulletins", "blurbs"):
        tab = "bulletins"
    page = request.args.get("page", 1, type=int)
    if tab == "bulletins":
        query = Bulletin.query.filter_by(user_id=user.id).order_by(Bulletin.timestamp.desc())
        items, page, total_pages, total_items = _paginate_query(query, page, UPDATES_PER_PAGE)
    else:
        query = Post.query.filter_by(user_id=user.id).order_by(Post.timestamp.desc())
        items, page, total_pages, total_items = _paginate_query(query, page, UPDATES_PER_PAGE)
    return render_template(
        "profile_updates.html",
        user=user,
        tab=tab,
        items=items,
        is_owner=is_owner,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
    )

@app.route("/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        current_user.bio = request.form.get("bio", "")
        current_user.ideal_meet = request.form.get("ideal_meet", "")[:500]
        current_user.city, current_user.state, current_user.zip_code = parse_location_fields(
            request.form.get("city", ""),
            request.form.get("state", ""),
            request.form.get("zip_code", ""),
        )
        current_user.bg_color = request.form.get("bg_color", SITE_DEFAULTS["bg_color"])
        new_song = extract_url(request.form.get("profile_song", "")).strip()
        if new_song != (current_user.profile_song or ""):
            if _is_local_profile_song(current_user.profile_song):
                delete_profile_song_file(current_user.profile_song)
            current_user.profile_song = new_song
            current_user.youtube_url = ""
            current_user.spotify_url = ""
        mf = request.form.get("msg_filter", "open")
        current_user.msg_filter = mf if mf in ("open", "verified", "crew") else "open"
        current_user.away_message = request.form.get("away_message", "")[:200]
        submitted_mood = request.form.get("mood", "")
        current_user.mood = submitted_mood if submitted_mood in VALID_MOODS else ""
        current_user.polls_enabled = request.form.get("polls_enabled") == "on"
        current_user.show_daily_quote = request.form.get("show_daily_quote") == "on"
        set_updates_opt_in(current_user, request.form.get("updates_opt_in") == "on")
        current_user.song_autoplay = request.form.get("song_autoplay") == "on"
        tc = request.form.get("theme_color", SITE_DEFAULTS["theme_color"])
        current_user.theme_color = tc if (len(tc) == 7 and tc.startswith("#")) else SITE_DEFAULTS["theme_color"]
        VALID_FONTS = ["Arial", "Georgia", "Verdana", "Trebuchet MS", "Courier New", "Times New Roman"]
        fc = request.form.get("font_choice", "Arial")
        current_user.font_choice = fc if fc in VALID_FONTS else "Arial"
        preset_key = request.form.get("theme_preset", "").strip()
        if preset_key in PROFILE_THEME_PRESETS:
            preset = PROFILE_THEME_PRESETS[preset_key]
            current_user.bg_color = preset["bg_color"]
            current_user.theme_color = preset["theme_color"]
            current_user.font_choice = preset["font_choice"]
            current_user.dark_mode = preset["dark_mode"]
            current_user.profile_theme = preset_key
        else:
            current_user.profile_theme = "custom" if preset_key == "custom" else (current_user.profile_theme or "")
        raw_css = request.form.get("custom_css", "")
        current_user.custom_css = sanitize_profile_css(raw_css)
        if request.files.get("profile_pic"):
            pic = request.files["profile_pic"]
            if pic.filename != "":
                try:
                    url, _ = upload_to_cloudinary(pic, "profile_pics", resize=(150, 150))
                    current_user.profile_pic = url
                except Exception:
                    flash("Profile pic upload failed. Try again.", "danger")
        if request.files.get("bg_image"):
            bg = request.files["bg_image"]
            if bg.filename != "":
                try:
                    url, _ = upload_to_cloudinary(bg, "backgrounds")
                    current_user.bg_image = url
                except Exception:
                    flash("Background upload failed. Try again.", "danger")
        db.session.commit()
        flash("Profile updated!", "success")
        return redirect(url_for("profile", username=current_user.username))
    invites = Invite.query.filter_by(created_by=current_user.id).order_by(Invite.created_at.desc()).all()
    return render_template(
        "edit_profile.html",
        mood_options=MOOD_OPTIONS,
        invites=invites,
        profile_music_link=profile_music_link_value(current_user),
        theme_presets=PROFILE_THEME_PRESETS,
        us_states=US_STATES,
    )

def get_crew_status(current_user_id, profile_user_id):
    req = CrewRequest.query.filter(
        ((CrewRequest.from_id == current_user_id) & (CrewRequest.to_id == profile_user_id)) |
        ((CrewRequest.from_id == profile_user_id) & (CrewRequest.to_id == current_user_id))
    ).first()
    return req

def get_user_crew(user_id):
    """Accepted crew members for a user, sorted by username."""
    crew = CrewRequest.query.filter(
        ((CrewRequest.from_id == user_id) | (CrewRequest.to_id == user_id)),
        CrewRequest.status == "accepted"
    ).all()
    members, seen = [], set()
    for r in crew:
        member = r.to_user if r.from_id == user_id else r.from_user
        if member.id not in seen:
            members.append(member)
            seen.add(member.id)
    return sorted(members, key=lambda m: m.username.lower())

def get_mutual_crew_count(viewer_id, profile_id):
    if viewer_id == profile_id:
        return 0
    crew_a = {m.id for m in get_user_crew(viewer_id)}
    crew_b = {m.id for m in get_user_crew(profile_id)}
    return len(crew_a & crew_b)

@app.route("/crew/add/<int:user_id>", methods=["POST"])
@login_required
def crew_add(user_id):
    target = User.query.get_or_404(user_id)
    existing = get_crew_status(current_user.id, user_id)
    if not existing:
        req = CrewRequest(from_id=current_user.id, to_id=user_id, status="pending")
        db.session.add(req)
        db.session.commit()
    return redirect(url_for("profile", username=target.username))

@app.route("/crew/accept/<int:request_id>", methods=["POST"])
@login_required
def crew_accept(request_id):
    req = CrewRequest.query.get_or_404(request_id)
    if req.to_id != current_user.id:
        return redirect(url_for("profile", username=current_user.username))
    req.status = "accepted"
    db.session.commit()
    return redirect(url_for("profile", username=current_user.username))

@app.route("/crew/remove/<int:user_id>", methods=["POST"])
@login_required
def crew_remove(user_id):
    target = User.query.get_or_404(user_id)
    req = get_crew_status(current_user.id, user_id)
    if req:
        db.session.delete(req)
        db.session.commit()
    return redirect(url_for("profile", username=target.username))

@app.route("/crew/block/<int:user_id>", methods=["POST"])
@login_required
def crew_block(user_id):
    target = User.query.get_or_404(user_id)
    req = get_crew_status(current_user.id, user_id)
    if req:
        req.status = "blocked"
        req.from_id = current_user.id
        req.to_id = user_id
    else:
        req = CrewRequest(from_id=current_user.id, to_id=user_id, status="blocked")
        db.session.add(req)
    db.session.commit()
    return redirect(url_for("profile", username=target.username))

@app.route("/crew/requests")
@login_required
def crew_requests():
    pending = CrewRequest.query.filter_by(to_id=current_user.id, status="pending").all()
    return render_template("crew_requests.html", pending=pending)

@app.route("/top8", methods=["GET", "POST"])
@login_required
def top8():
    crew = CrewRequest.query.filter(
        ((CrewRequest.from_id == current_user.id) | (CrewRequest.to_id == current_user.id)),
        CrewRequest.status == "accepted"
    ).all()
    crew_members = []
    for r in crew:
        member = r.to_user if r.from_id == current_user.id else r.from_user
        crew_members.append(member)

    if request.method == "POST":
        selected = request.form.getlist("top8")[:8]
        current_user.top8 = ",".join(selected)
        db.session.commit()
        flash("Top 8 updated!", "success")
        return redirect(url_for("profile", username=current_user.username))
    current_top8 = current_user.top8.split(",") if current_user.top8 else []
    return render_template("top8.html", crew_members=crew_members, current_top8=current_top8)

@app.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        return redirect(url_for("profile", username=current_user.username))
    db.session.delete(post)
    db.session.commit()
    return redirect(url_for("profile", username=current_user.username))

@app.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        return redirect(url_for("profile", username=current_user.username))
    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if not body:
            flash("Post cannot be empty.", "danger")
            return redirect(url_for("edit_post", post_id=post_id))
        post.body = body
        db.session.commit()
        return redirect(url_for("profile", username=current_user.username))
    return render_template("edit_post.html", post=post)

@app.route("/bulletin/create", methods=["POST"])
@login_required
def bulletin_create():
    body = request.form.get("body", "").strip()
    if not body:
        flash("Bulletin cannot be empty.", "danger")
        return redirect(url_for("profile", username=current_user.username) + "#updates")
    bulletin = Bulletin(body=body[:BULLETIN_MAX_LEN], user_id=current_user.id)
    db.session.add(bulletin)
    db.session.commit()
    return redirect(url_for("profile", username=current_user.username) + "#updates")

@app.route("/bulletin/<int:bulletin_id>/delete", methods=["POST"])
@login_required
def bulletin_delete(bulletin_id):
    bulletin = Bulletin.query.get_or_404(bulletin_id)
    if bulletin.user_id != current_user.id:
        return redirect(url_for("profile", username=current_user.username))
    db.session.delete(bulletin)
    db.session.commit()
    return redirect(url_for("profile", username=current_user.username) + "#updates")

@app.route("/post/create", methods=["POST"])
@login_required
def create_post():
    body = request.form.get("body", "").strip()
    if not body:
        flash("Post cannot be empty.", "danger")
        return redirect(url_for("profile", username=current_user.username))
    post = Post(body=body, user_id=current_user.id)
    if request.files.get("post_image"):
        img = request.files["post_image"]
        if img.filename != "":
            try:
                url, _ = upload_to_cloudinary(img, "post_images")
                post.image = url
            except Exception:
                flash("Image upload failed — post saved without image.", "danger")
    db.session.add(post)
    db.session.commit()
    return redirect(url_for("profile", username=current_user.username) + "?open=blurbs#updates")

@app.route("/profile/<username>/comment", methods=["POST"])
@login_required
def add_comment(username):
    user = User.query.filter_by(username=username).first_or_404()
    body = request.form.get("body", "").strip()
    if not body:
        flash("Comment cannot be empty.", "danger")
        return redirect(url_for("profile", username=username))
    comment = Comment(body=body, author_id=current_user.id, profile_id=user.id)
    db.session.add(comment)
    db.session.commit()
    return redirect(url_for("profile", username=username) + "#comments")

@app.before_request
def update_last_seen():
    if current_user.is_authenticated:
        try:
            current_user.last_seen = datetime.utcnow()
            db.session.commit()
        except Exception:
            db.session.rollback()

@app.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return render_template("search.html", results=[], crew_statuses={}, query=q)
    results = (User.query.filter(
        User.id != current_user.id,
        User.username.ilike(f"%{q}%"),
    ).order_by(User.username).limit(50).all())
    crew_statuses = {}
    for u in results:
        rel = CrewRequest.query.filter(
            ((CrewRequest.from_id == current_user.id) & (CrewRequest.to_id == u.id)) |
            ((CrewRequest.from_id == u.id) & (CrewRequest.to_id == current_user.id))
        ).first()
        crew_statuses[u.id] = rel.status if rel else None
    return render_template("search.html", results=results, crew_statuses=crew_statuses, query=q)

def _check_msg_access(other):
    """Return None if access granted, or a redirect response if blocked."""
    f = other.msg_filter or "open"
    if f == "open":
        return None
    if f == "crew":
        req = get_crew_status(current_user.id, other.id)
        if req and req.status == "accepted":
            return None
        flash(f"{other.username} only accepts messages from their crew.", "danger")
        return redirect(url_for("profile", username=other.username))
    if f == "verified":
        flag = f"verified_for_{other.id}"
        if session.get(flag):
            return None
        return redirect(url_for("chat_verify", username=other.username))
    return None

@app.route("/chat/<username>")
@login_required
def chat(username):
    other = User.query.filter_by(username=username).first_or_404()
    if other.id == current_user.id:
        return redirect(url_for("profile", username=current_user.username))
    blocked = _check_msg_access(other)
    if blocked:
        return blocked
    messages = DirectMessage.query.filter(
        ((DirectMessage.from_id == current_user.id) & (DirectMessage.to_id == other.id)) |
        ((DirectMessage.from_id == other.id) & (DirectMessage.to_id == current_user.id))
    ).order_by(DirectMessage.timestamp.asc()).all()
    # Mark incoming messages as read
    DirectMessage.query.filter_by(from_id=other.id, to_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return render_template("chat.html", other=other, messages=messages)

@app.route("/chat/<username>/verify", methods=["GET", "POST"])
@login_required
def chat_verify(username):
    other = User.query.filter_by(username=username).first_or_404()
    if other.id == current_user.id:
        return redirect(url_for("profile", username=current_user.username))
    if (other.msg_filter or "open") != "verified":
        return redirect(url_for("chat", username=username))
    if request.method == "POST":
        answer = request.form.get("answer", "").strip()
        correct = str(session.get(f"verify_answer_{other.id}", ""))
        if answer == correct:
            session[f"verified_for_{other.id}"] = True
            return redirect(url_for("chat", username=username))
        flash("Wrong answer — try again.", "danger")
    a = random.randint(1, 12)
    b = random.randint(1, 12)
    session[f"verify_answer_{other.id}"] = a + b
    return render_template("verify.html", other=other, a=a, b=b)

@app.route("/chat/<username>/send", methods=["POST"])
@login_required
def chat_send(username):
    other = User.query.filter_by(username=username).first_or_404()
    if other.id == current_user.id:
        return redirect(url_for("profile", username=current_user.username))
    blocked = _check_msg_access(other)
    if blocked:
        return blocked
    body = request.form.get("body", "").strip()
    if body:
        msg = DirectMessage(from_id=current_user.id, to_id=other.id, body=body)
        db.session.add(msg)
        db.session.commit()
    return redirect(url_for("chat", username=username))

@app.route("/chat/<username>/messages")
@login_required
def chat_messages(username):
    other = User.query.filter_by(username=username).first_or_404()
    after_id = request.args.get("after", 0, type=int)
    messages = DirectMessage.query.filter(
        ((DirectMessage.from_id == current_user.id) & (DirectMessage.to_id == other.id)) |
        ((DirectMessage.from_id == other.id) & (DirectMessage.to_id == current_user.id)),
        DirectMessage.id > after_id
    ).order_by(DirectMessage.timestamp.asc()).all()
    return jsonify([{
        "id": m.id,
        "from": m.sender.username,
        "body": m.body,
        "time": m.timestamp.strftime("%b %d at %I:%M %p")
    } for m in messages])

@app.route("/inbox/unread")
@login_required
def inbox_unread():
    """Returns unread message count and per-sender breakdown. Used by global nav poller."""
    unread = DirectMessage.query.filter_by(to_id=current_user.id, is_read=False).all()
    by_sender = {}
    for m in unread:
        by_sender[m.sender.username] = by_sender.get(m.sender.username, 0) + 1
    # T024 — polls badge count (unanswered eligible polls)
    polls_count = 0
    if current_user.polls_enabled and (current_user.msg_filter or 'open') != 'verified':
        eligible = _get_eligible_polls(current_user)
        if eligible:
            voted_ids = {v.poll_id for v in PollVote.query.filter_by(user_id=current_user.id).all()}
            polls_count = sum(1 for p in eligible if p.id not in voted_ids)
    return jsonify({
        "count": len(unread),
        "senders": [{"username": u, "count": c} for u, c in by_sender.items()],
        "dnd": (current_user.status == "dnd"),
        "polls_count": polls_count
    })

@app.route("/inbox/conversations")
@login_required
def inbox_conversations():
    """Returns all conversations (last message + unread count) for the floating inbox panel."""
    # Find all users the current user has exchanged messages with
    sent = db.session.query(DirectMessage.to_id).filter_by(from_id=current_user.id)
    received = db.session.query(DirectMessage.from_id).filter_by(to_id=current_user.id)
    partner_ids = {r[0] for r in sent.union(received).all()} - {current_user.id}

    convos = []
    for pid in partner_ids:
        partner = db.session.get(User, pid)
        if not partner:
            continue
        last_msg = DirectMessage.query.filter(
            ((DirectMessage.from_id == current_user.id) & (DirectMessage.to_id == pid)) |
            ((DirectMessage.from_id == pid) & (DirectMessage.to_id == current_user.id))
        ).order_by(DirectMessage.timestamp.desc()).first()
        unread_count = DirectMessage.query.filter_by(from_id=pid, to_id=current_user.id, is_read=False).count()
        if last_msg:
            convos.append({
                "username": partner.username,
                "unread": unread_count,
                "last_body": last_msg.body[:50],
                "last_time": last_msg.timestamp.strftime("%b %d at %I:%M %p")
            })
    convos.sort(key=lambda x: x["unread"], reverse=True)
    return jsonify(convos)

@app.route("/icq/buddies")
@login_required
def icq_buddies():
    """Crew buddy list with online status for ICQ-style panel."""
    crew = get_user_crew(current_user.id)
    buddies = []
    for member in crew:
        pic = member.profile_pic or ""
        buddies.append({
            "username": member.username,
            "status": member.status or "online",
            "mood": member.mood or "",
            "profile_pic": pic if pic.startswith("http") else "",
        })
    buddies.sort(key=lambda b: ({"online": 0, "away": 1, "dnd": 2}.get(b["status"], 3), b["username"]))
    return jsonify(buddies)

@app.route("/inbox/read/<username>", methods=["POST"])
@login_required
def inbox_mark_read(username):
    """Mark all messages from username as read (called when opening chat in floating window)."""
    other = User.query.filter_by(username=username).first_or_404()
    DirectMessage.query.filter_by(from_id=other.id, to_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"ok": True})

# T021 — mood options: key stored in DB, value displayed in templates
MOOD_OPTIONS = [
    ("",              "— No mood set —"),
    ("happy",         "😊 Happy"),
    ("excited",       "😂 Excited"),
    ("loved_up",      "😍 Loved Up"),
    ("celebratory",   "🥳 Celebratory"),
    ("cool",          "😎 Cool"),
    ("thoughtful",    "🤔 Thoughtful"),
    ("bored",         "🥱 Bored"),
    ("tired",         "😴 Tired"),
    ("anxious",       "😰 Anxious"),
    ("sad",           "😢 Sad"),
    ("angry",         "😤 Angry"),
    ("dead_inside",   "💀 Dead Inside"),
]
VALID_MOODS = {key for key, _ in MOOD_OPTIONS}

MOVIE_QUOTE_PACK = {
    "quote_ill_be_back": {
        "label": "I'll Be Back",
        "movie": "Terminator",
        "text": "I'll be back.",
        "voice": "am_adam",
        "icon": "🤖",
    },
    "quote_hasta_la_vista": {
        "label": "Hasta La Vista",
        "movie": "Terminator 2",
        "text": "Hasta la vista, baby.",
        "voice": "am_adam",
        "icon": "😎",
    },
    "quote_force": {
        "label": "May The Force",
        "movie": "Star Wars",
        "text": "May the Force be with you.",
        "voice": "bm_george",
        "icon": "⭐",
    },
    "quote_no_i_am": {
        "label": "I Am Your Father",
        "movie": "Star Wars",
        "text": "No. I am your father.",
        "voice": "am_adam",
        "icon": "🌌",
    },
    "quote_houston": {
        "label": "Houston Problem",
        "movie": "Apollo 13",
        "text": "Houston, we have a problem.",
        "voice": "am_michael",
        "icon": "🚀",
    },
    "quote_little_friend": {
        "label": "Little Friend",
        "movie": "Scarface",
        "text": "Say hello to my little friend!",
        "voice": "am_adam",
        "icon": "💥",
    },
    "quote_truth": {
        "label": "The Truth",
        "movie": "A Few Good Men",
        "text": "You can't handle the truth!",
        "voice": "am_adam",
        "icon": "⚖️",
    },
    "quote_show_money": {
        "label": "Show Me The Money",
        "movie": "Jerry Maguire",
        "text": "Show me the money!",
        "voice": "am_michael",
        "icon": "💰",
    },
    "quote_chocolates": {
        "label": "Box of Chocolates",
        "movie": "Forrest Gump",
        "text": "Life is like a box of chocolates.",
        "voice": "bm_george",
        "icon": "🍫",
    },
    "quote_king_world": {
        "label": "King of the World",
        "movie": "Titanic",
        "text": "I'm the king of the world!",
        "voice": "am_michael",
        "icon": "🚢",
    },
    "quote_serious": {
        "label": "Why So Serious",
        "movie": "The Dark Knight",
        "text": "Why so serious?",
        "voice": "am_adam",
        "icon": "🃏",
    },
    "quote_johnny": {
        "label": "Here's Johnny",
        "movie": "The Shining",
        "text": "Here's Johnny!",
        "voice": "am_adam",
        "icon": "🪓",
    },
    "quote_james_bond": {
        "label": "Bond. James Bond.",
        "movie": "007",
        "text": "Bond. James Bond.",
        "voice": "bm_george",
        "icon": "🍸",
    },
    "quote_yeah_baby": {
        "label": "Yeah Baby",
        "movie": "Austin Powers",
        "text": "Yeah baby, yeah!",
        "voice": "bm_george",
        "icon": "🕺",
    },
    "quote_run_forrest": {
        "label": "Run Forrest Run",
        "movie": "Forrest Gump",
        "text": "Run, Forrest, run!",
        "voice": "af_sarah",
        "icon": "🏃",
    },
    "quote_red_pill": {
        "label": "Red Pill",
        "movie": "The Matrix",
        "text": "You take the red pill.",
        "voice": "am_adam",
        "icon": "💊",
    },
}

VALID_BUILTIN_SOUNDS = {
    "none", "classic_beep", "double_ping", "triple_beep", "rising_tone",
    "falling_tone", "soft_chime", "retro_game", "soft_pop", "ding",
    "deep_bong", "fast_blip", "old_phone", "doorbell", "laser", "win95",
    "icq_uhoh", "icq_door_open", "icq_door_close", "icq_send", "icq_online",
    "custom",
} | set(MOVIE_QUOTE_PACK.keys())

MAX_USER_SOUNDS = 20
MAX_USER_SOUND_BYTES = 500_000
MAX_USER_SOUND_B64 = 700_000
MAX_CUSTOM_SOUND_B64 = MAX_USER_SOUND_B64
MAX_TTS_CHARS = 200
ALLOWED_SOUND_MIMES = {
    "audio/mpeg", "audio/mp3", "audio/ogg", "audio/wav", "audio/x-wav",
    "audio/webm", "audio/mp4", "audio/x-m4a", "audio/m4a",
}


def user_sound_key(sound_id):
    return f"us_{sound_id}"


def parse_user_sound_key(key):
    if not key or not key.startswith("us_"):
        return None
    try:
        return int(key[3:])
    except ValueError:
        return None


def get_user_sound_for_key(user, key):
    sid = parse_user_sound_key(key)
    if sid is None:
        return None
    return UserSound.query.filter_by(id=sid, user_id=user.id).first()


def is_valid_alert_sound(user, key):
    if key in VALID_BUILTIN_SOUNDS:
        return True
    return get_user_sound_for_key(user, key) is not None


def resolve_alert_audio(user, key):
    if key == "custom":
        return user.custom_sound or ""
    snd = get_user_sound_for_key(user, key)
    return snd.audio_data if snd else ""


def add_user_sound(user, label, data_uri, source):
    if user.sound_library.count() >= MAX_USER_SOUNDS:
        return None, "Soundboard full — delete a clip to add more (max 20)."
    if not data_uri or not data_uri.startswith("data:"):
        return None, "Invalid audio data."
    if len(data_uri) > MAX_USER_SOUND_B64:
        return None, "Clip too large — max ~500KB."
    label = (label or "My Sound").strip()[:60] or "My Sound"
    snd = UserSound(user_id=user.id, label=label, audio_data=data_uri, source=source)
    db.session.add(snd)
    db.session.commit()
    return snd, None


def file_to_data_uri(data, content_type):
    import base64
    mime = content_type or "audio/mpeg"
    if mime not in ALLOWED_SOUND_MIMES:
        ext = mime.split("/")[-1] if "/" in mime else "mpeg"
        mime = f"audio/{ext}"
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{b64}"


@app.route("/sounds", methods=["GET", "POST"])
@login_required
def sounds():
    from kokoro_tts import KOKORO_VOICES, models_available, synthesize_data_uri

    if request.method == "POST":
        action = request.form.get("action", "select")
        if action == "select":
            s = request.form.get("alert_sound", "classic_beep")
            current_user.alert_sound = s if is_valid_alert_sound(current_user, s) else "classic_beep"
            db.session.commit()
            flash("Alert sound saved!", "success")
        elif action in ("upload", "library_upload"):
            f = request.files.get("sound_file")
            label = request.form.get("label", "").strip()
            if f and f.filename:
                data = f.read()
                if len(data) > MAX_USER_SOUND_BYTES:
                    flash("File too large — max ~500KB.", "danger")
                else:
                    data_uri = file_to_data_uri(data, f.content_type)
                    snd, err = add_user_sound(current_user, label or f.filename, data_uri, "upload")
                    if err:
                        flash(err, "danger")
                    else:
                        current_user.alert_sound = user_sound_key(snd.id)
                        db.session.commit()
                        flash("Sound imported to your soundboard!", "success")
            else:
                flash("No file selected.", "danger")
        elif action in ("record", "library_record"):
            b64_data = request.form.get("recorded_sound", "")
            label = request.form.get("label", "Recording").strip()
            if b64_data and len(b64_data) <= MAX_USER_SOUND_B64:
                snd, err = add_user_sound(current_user, label, b64_data, "record")
                if err:
                    flash(err, "danger")
                else:
                    current_user.alert_sound = user_sound_key(snd.id)
                    db.session.commit()
                    flash("Recording saved to your soundboard!", "success")
            elif len(b64_data) > MAX_USER_SOUND_B64:
                flash("Recording too long — max ~15 seconds / 500KB.", "danger")
            else:
                flash("No recording data.", "danger")
        elif action == "library_tts":
            text = request.form.get("tts_text", "").strip()
            voice = request.form.get("tts_voice", "af_heart")
            label = request.form.get("label", "").strip() or text[:40]
            valid_voices = {v[0] for v in KOKORO_VOICES}
            if voice not in valid_voices:
                voice = "af_heart"
            if not text:
                flash("Type something for Kokoro to say.", "danger")
            elif len(text) > MAX_TTS_CHARS:
                flash(f"Keep it under {MAX_TTS_CHARS} characters.", "danger")
            elif not models_available():
                flash("Kokoro TTS models not installed on server — record or import instead.", "danger")
            else:
                try:
                    data_uri = synthesize_data_uri(text, voice=voice)
                    snd, err = add_user_sound(current_user, label, data_uri, "tts")
                    if err:
                        flash(err, "danger")
                    else:
                        current_user.alert_sound = user_sound_key(snd.id)
                        db.session.commit()
                        flash("Kokoro clip added to your soundboard!", "success")
                except Exception as exc:
                    flash(f"Kokoro TTS failed: {exc}", "danger")
        elif action == "library_delete":
            sid = request.form.get("sound_id", type=int)
            snd = UserSound.query.filter_by(id=sid, user_id=current_user.id).first()
            if snd:
                key = user_sound_key(snd.id)
                if current_user.alert_sound == key:
                    current_user.alert_sound = "classic_beep"
                db.session.delete(snd)
                db.session.commit()
                flash("Clip removed.", "success")
            else:
                flash("Clip not found.", "danger")
        return redirect(url_for("sounds"))

    library = current_user.sound_library.all()
    return render_template(
        "sounds.html",
        movie_quote_pack=MOVIE_QUOTE_PACK,
        sound_library=library,
        kokoro_voices=KOKORO_VOICES,
        kokoro_available=models_available(),
        max_user_sounds=MAX_USER_SOUNDS,
    )

@app.route("/mood", methods=["POST"])
@login_required
def set_mood():
    m = request.form.get("mood", "")
    current_user.mood = m if m in VALID_MOODS else ""
    db.session.commit()
    return redirect(url_for("profile", username=current_user.username))

@app.route("/status", methods=["POST"])
@login_required
def set_status():
    s = request.form.get("status", "online")
    if s in ("online", "away", "dnd"):
        current_user.status = s
        db.session.commit()
    return redirect(request.referrer or url_for("profile", username=current_user.username))


@app.route("/toggle-dark-mode", methods=["POST"])
@login_required
def toggle_dark_mode():
    current_user.dark_mode = not current_user.dark_mode
    db.session.commit()
    return redirect(request.referrer or url_for("profile", username=current_user.username))

# ── T022: Photo Albums ────────────────────────────────────────────────────────

@app.route("/album/create", methods=["POST"])
@login_required
def album_create():
    name = request.form.get("name", "").strip()[:100]
    if not name:
        flash("Album name cannot be empty.", "danger")
        return redirect(url_for("profile", username=current_user.username))
    album = PhotoAlbum(user_id=current_user.id, name=name)
    db.session.add(album)
    db.session.commit()
    return redirect(url_for("album_view", album_id=album.id))

@app.route("/album/<int:album_id>")
def album_view(album_id):
    album = PhotoAlbum.query.get_or_404(album_id)
    is_owner = current_user.is_authenticated and current_user.id == album.user_id
    return render_template("album.html", album=album, is_owner=is_owner)

@app.route("/album/<int:album_id>/upload", methods=["POST"])
@login_required
def album_upload(album_id):
    album = PhotoAlbum.query.get_or_404(album_id)
    if album.user_id != current_user.id:
        flash("Not your album.", "danger")
        return redirect(url_for("album_view", album_id=album_id))
    files = request.files.getlist("photos")
    caption = request.form.get("caption", "").strip()[:200]
    uploaded = 0
    for f in files:
        if f and f.filename:
            try:
                url, public_id = upload_to_cloudinary(f, f"albums/{current_user.id}")
                photo = Photo(album_id=album.id, url=url, public_id=public_id, caption=caption)
                db.session.add(photo)
                uploaded += 1
            except Exception:
                flash(f"One file failed to upload — skipped.", "danger")
    if uploaded:
        db.session.commit()
        flash(f"{uploaded} photo(s) added.", "success")
    return redirect(url_for("album_view", album_id=album_id))

@app.route("/album/<int:album_id>/delete", methods=["POST"])
@login_required
def album_delete(album_id):
    album = PhotoAlbum.query.get_or_404(album_id)
    if album.user_id != current_user.id:
        flash("Not your album.", "danger")
        return redirect(url_for("profile", username=current_user.username))
    # Delete photos from Cloudinary
    for photo in album.photos:
        try:
            cloudinary.uploader.destroy(photo.public_id)
        except Exception:
            pass  # Log and continue — DB record still gets deleted
    db.session.delete(album)
    db.session.commit()
    flash("Album deleted.", "success")
    return redirect(url_for("profile", username=current_user.username))

# ── Photo Montage ─────────────────────────────────────────────────────────────

@app.route("/montage/edit", methods=["GET", "POST"])
@login_required
def montage_edit():
    montage = get_or_create_montage(current_user)
    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "save":
            montage.title = (request.form.get("title") or "My Montage").strip()[:100]
            mode = request.form.get("music_mode", "profile")
            montage.music_mode = mode if mode in ("profile", "custom") else "profile"
            montage.song_1 = extract_url(request.form.get("song_1", "")).strip()
            montage.song_2 = extract_url(request.form.get("song_2", "")).strip()
            try:
                interval = int(request.form.get("interval_sec", 4))
            except ValueError:
                interval = 4
            montage.interval_sec = max(2, min(12, interval))
            montage.show_on_profile = request.form.get("show_on_profile") == "on"
            montage.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Montage settings saved.", "success")
        return redirect(url_for("montage_edit"))

    album_photos = (
        Photo.query.join(PhotoAlbum)
        .filter(PhotoAlbum.user_id == current_user.id)
        .order_by(Photo.created_at.desc())
        .all()
    )
    profile_song_preview = profile_music_link_value(current_user)
    return render_template(
        "montage_edit.html",
        montage=montage,
        album_photos=album_photos,
        profile_song_preview=profile_song_preview,
        max_slides=MONTAGE_MAX_SLIDES,
    )


@app.route("/montage/slide/upload", methods=["POST"])
@login_required
def montage_slide_upload():
    montage = get_or_create_montage(current_user)
    if len(montage.slides) >= MONTAGE_MAX_SLIDES:
        flash(f"Montage is full ({MONTAGE_MAX_SLIDES} photos max). Remove one first.", "danger")
        return redirect(url_for("montage_edit"))
    files = request.files.getlist("photos")
    caption = request.form.get("caption", "").strip()[:200]
    uploaded = 0
    next_order = (max((s.sort_order for s in montage.slides), default=-1) + 1)
    for f in files:
        if not f or not f.filename:
            continue
        if len(montage.slides) + uploaded >= MONTAGE_MAX_SLIDES:
            break
        try:
            url, public_id = upload_to_cloudinary(f, f"montage/{current_user.id}")
            slide = MontageSlide(
                montage_id=montage.id, url=url, public_id=public_id,
                caption=caption, sort_order=next_order + uploaded,
                source="upload",
            )
            db.session.add(slide)
            uploaded += 1
        except Exception:
            flash("One photo failed to upload — skipped.", "danger")
    if uploaded:
        montage.updated_at = datetime.utcnow()
        db.session.commit()
        flash(f"{uploaded} photo(s) added to montage.", "success")
    return redirect(url_for("montage_edit"))


@app.route("/montage/slide/add-album", methods=["POST"])
@login_required
def montage_slide_add_album():
    montage = get_or_create_montage(current_user)
    if len(montage.slides) >= MONTAGE_MAX_SLIDES:
        flash(f"Montage is full ({MONTAGE_MAX_SLIDES} photos max).", "danger")
        return redirect(url_for("montage_edit"))
    photo_id = request.form.get("photo_id", type=int)
    photo = Photo.query.get_or_404(photo_id)
    album = PhotoAlbum.query.get_or_404(photo.album_id)
    if album.user_id != current_user.id:
        flash("That photo is not yours.", "danger")
        return redirect(url_for("montage_edit"))
    if MontageSlide.query.filter_by(montage_id=montage.id, source_photo_id=photo.id).first():
        flash("That photo is already in your montage.", "warning")
        return redirect(url_for("montage_edit"))
    next_order = max((s.sort_order for s in montage.slides), default=-1) + 1
    slide = MontageSlide(
        montage_id=montage.id, url=photo.url, public_id=photo.public_id,
        caption=photo.caption or "", sort_order=next_order,
        source="album", source_photo_id=photo.id,
    )
    db.session.add(slide)
    montage.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Photo added from album.", "success")
    return redirect(url_for("montage_edit"))


def _montage_slide_owned(slide_id):
    slide = MontageSlide.query.get_or_404(slide_id)
    montage = PhotoMontage.query.get_or_404(slide.montage_id)
    if montage.user_id != current_user.id:
        flash("Not your montage.", "danger")
        return None, None
    return slide, montage


@app.route("/montage/slide/<int:slide_id>/delete", methods=["POST"])
@login_required
def montage_slide_delete(slide_id):
    slide, montage = _montage_slide_owned(slide_id)
    if not slide:
        return redirect(url_for("montage_edit"))
    if slide.source == "upload" and slide.public_id:
        try:
            cloudinary.uploader.destroy(slide.public_id)
        except Exception:
            pass
    db.session.delete(slide)
    montage.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Photo removed from montage.", "success")
    return redirect(url_for("montage_edit"))


@app.route("/montage/slide/<int:slide_id>/move", methods=["POST"])
@login_required
def montage_slide_move(slide_id):
    direction = request.form.get("direction", "")
    slide, montage = _montage_slide_owned(slide_id)
    if not slide:
        return redirect(url_for("montage_edit"))
    slides = sorted(montage.slides, key=lambda s: s.sort_order)
    idx = next((i for i, s in enumerate(slides) if s.id == slide.id), None)
    if idx is None:
        return redirect(url_for("montage_edit"))
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(slides):
        return redirect(url_for("montage_edit"))
    slides[idx].sort_order, slides[swap_idx].sort_order = (
        slides[swap_idx].sort_order, slides[idx].sort_order,
    )
    montage.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("montage_edit"))


@app.route("/profile/<username>/montage")
def profile_montage(username):
    user = User.query.filter_by(username=username).first_or_404()
    montage = PhotoMontage.query.filter_by(user_id=user.id).first()
    if not montage or not montage.slides:
        flash("No montage to show yet.", "warning")
        return redirect(url_for("profile", username=username))
    is_owner = current_user.is_authenticated and current_user.id == user.id
    uses_custom = montage.music_mode == "custom" and bool(
        (montage.song_1 or "").strip() or (montage.song_2 or "").strip()
    )
    montage_music_items = get_montage_music_items(montage, user) if uses_custom else (
        get_user_music_items(user) if montage.music_mode == "profile" else []
    )
    if uses_custom and not montage_music_items:
        montage_music_items = get_user_music_items(user)
        montage_music_label = "fallback"
    elif uses_custom:
        montage_music_label = "custom"
    elif montage.music_mode == "profile" and montage_music_items:
        montage_music_label = "profile"
    else:
        montage_music_label = "none"
    return render_template(
        "montage_view.html",
        user=user,
        montage=montage,
        is_owner=is_owner,
        montage_music_items=montage_music_items,
        montage_music_label=montage_music_label,
    )


@app.route("/photo/<int:photo_id>/delete", methods=["POST"])
@login_required
def photo_delete(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    album = PhotoAlbum.query.get_or_404(photo.album_id)
    if album.user_id != current_user.id:
        flash("Not your photo.", "danger")
        return redirect(url_for("album_view", album_id=album.id))
    try:
        cloudinary.uploader.destroy(photo.public_id)
    except Exception:
        pass
    db.session.delete(photo)
    db.session.commit()
    return redirect(url_for("album_view", album_id=album.id))

# ── T024: Polls ──────────────────────────────────────────────────────────────

def _get_eligible_polls(user):
    """Return polls this user can see based on opt-in + message filter."""
    if not user.polls_enabled:
        return []
    f = user.msg_filter or 'open'
    if f == 'verified':
        return []
    if f == 'crew':
        crew_reqs = CrewRequest.query.filter(
            ((CrewRequest.from_id == user.id) | (CrewRequest.to_id == user.id)),
            CrewRequest.status == 'accepted'
        ).all()
        crew_ids = [r.to_id if r.from_id == user.id else r.from_id for r in crew_reqs]
        if not crew_ids:
            return []
        return Poll.query.filter(Poll.creator_id.in_(crew_ids)).order_by(Poll.created_at.desc()).all()
    return Poll.query.order_by(Poll.created_at.desc()).all()

@app.route("/polls")
@login_required
def polls():
    opted_in = bool(current_user.polls_enabled)
    poll_list = _get_eligible_polls(current_user) if opted_in else []
    # Map poll_id -> option_id the current user chose
    voted = {v.poll_id: v.option_id for v in PollVote.query.filter_by(user_id=current_user.id).all()}
    # Precompute vote counts: {poll_id: {option_id: count, '_total': total}}
    vote_counts = {}
    for poll in poll_list:
        counts = {}
        for vote in poll.votes:
            counts[vote.option_id] = counts.get(vote.option_id, 0) + 1
        counts['_total'] = sum(counts.values())
        vote_counts[poll.id] = counts
    return render_template("polls.html", poll_list=poll_list, voted=voted,
                           opted_in=opted_in, vote_counts=vote_counts)

@app.route("/polls/new", methods=["GET", "POST"])
@login_required
def polls_new():
    if request.method == "POST":
        question = request.form.get("question", "").strip()[:300]
        options  = [o.strip()[:200] for o in request.form.getlist("option") if o.strip()]
        if not question:
            flash("Question is required.", "danger")
            return redirect(url_for("polls_new"))
        if len(options) < 2:
            flash("You need at least 2 options.", "danger")
            return redirect(url_for("polls_new"))
        options = options[:20]
        poll = Poll(creator_id=current_user.id, question=question)
        db.session.add(poll)
        db.session.flush()
        for i, text in enumerate(options):
            db.session.add(PollOption(poll_id=poll.id, text=text, position=i))
        db.session.commit()
        flash("Poll created and live!", "success")
        return redirect(url_for("polls"))
    return render_template("polls_new.html")

@app.route("/polls/<int:poll_id>/vote", methods=["POST"])
@login_required
def polls_vote(poll_id):
    poll      = Poll.query.get_or_404(poll_id)
    option_id = request.form.get("option_id", type=int)
    if not option_id:
        flash("Select an option.", "danger")
        return redirect(url_for("polls"))
    option = PollOption.query.filter_by(id=option_id, poll_id=poll_id).first()
    if not option:
        flash("Invalid option.", "danger")
        return redirect(url_for("polls"))
    existing = PollVote.query.filter_by(poll_id=poll_id, user_id=current_user.id).first()
    if existing:
        flash("You already voted on that poll.", "info")
        return redirect(url_for("polls"))
    db.session.add(PollVote(poll_id=poll_id, user_id=current_user.id, option_id=option_id))
    db.session.commit()
    flash("Vote counted!", "success")
    return redirect(url_for("polls"))

@app.route("/polls/<int:poll_id>/delete", methods=["POST"])
@login_required
def polls_delete(poll_id):
    poll = Poll.query.get_or_404(poll_id)
    if poll.creator_id != current_user.id:
        flash("Not your poll.", "danger")
        return redirect(url_for("polls"))
    db.session.delete(poll)
    db.session.commit()
    flash("Poll deleted.", "success")
    return redirect(url_for("polls"))

# ── T023: Diary (private) & Blog (public) ────────────────────────────────────

def _save_entry_photos(entry, files, max_total=5):
    """Upload up to (max_total - existing) photos for an entry. Helper for diary + blog routes."""
    slots = max_total - len(entry.photos)
    for i, f in enumerate(files[:slots]):
        if f and f.filename:
            try:
                url, public_id = upload_to_cloudinary(f, f"journal/{entry.user_id}")
                ep = EntryPhoto(entry_id=entry.id, url=url, public_id=public_id,
                                position=len(entry.photos) + i)
                db.session.add(ep)
            except Exception:
                flash("One photo failed to upload — skipped.", "danger")

@app.route("/diary")
@login_required
def diary_index():
    entries = JournalEntry.query.filter_by(
        user_id=current_user.id, entry_type="diary"
    ).order_by(JournalEntry.created_at.desc()).all()
    return render_template("diary_index.html", entries=entries)

@app.route("/diary/new", methods=["GET", "POST"])
@login_required
def diary_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:200]
        body  = request.form.get("body", "").strip()
        if not title or not body:
            flash("Title and body are required.", "danger")
            return redirect(url_for("diary_new"))
        entry = JournalEntry(user_id=current_user.id, title=title,
                             body=body, entry_type="diary")
        db.session.add(entry)
        db.session.flush()  # need entry.id for photos
        _save_entry_photos(entry, request.files.getlist("photos"))
        db.session.commit()
        flash("Diary entry saved!", "success")
        return redirect(url_for("diary_view", entry_id=entry.id))
    return render_template("diary_write.html", entry=None, mode="new")

@app.route("/diary/<int:entry_id>")
@login_required
def diary_view(entry_id):
    entry = JournalEntry.query.get_or_404(entry_id)
    if entry.entry_type != "diary" or entry.user_id != current_user.id:
        return "Access denied — diary entries are private.", 403
    return render_template("diary_entry.html", entry=entry)

@app.route("/diary/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
def diary_edit(entry_id):
    entry = JournalEntry.query.get_or_404(entry_id)
    if entry.entry_type != "diary" or entry.user_id != current_user.id:
        return "Access denied.", 403
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:200]
        body  = request.form.get("body", "").strip()
        if not title or not body:
            flash("Title and body are required.", "danger")
            return redirect(url_for("diary_edit", entry_id=entry_id))
        entry.title = title
        entry.body  = body
        entry.updated_at = datetime.utcnow()
        _save_entry_photos(entry, request.files.getlist("photos"))
        db.session.commit()
        flash("Entry updated!", "success")
        return redirect(url_for("diary_view", entry_id=entry_id))
    return render_template("diary_write.html", entry=entry, mode="edit")

@app.route("/diary/<int:entry_id>/delete", methods=["POST"])
@login_required
def diary_delete(entry_id):
    entry = JournalEntry.query.get_or_404(entry_id)
    if entry.entry_type != "diary" or entry.user_id != current_user.id:
        return "Access denied.", 403
    for ep in entry.photos:
        try:
            cloudinary.uploader.destroy(ep.public_id)
        except Exception:
            pass
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted.", "success")
    return redirect(url_for("diary_index"))

@app.route("/blog/<username>")
def blog_index(username):
    user = User.query.filter_by(username=username).first_or_404()
    entries = JournalEntry.query.filter_by(
        user_id=user.id, entry_type="blog"
    ).order_by(JournalEntry.created_at.desc()).all()
    is_owner = current_user.is_authenticated and current_user.id == user.id
    return render_template("blog_index.html", user=user, entries=entries, is_owner=is_owner)

@app.route("/blog/<username>/new", methods=["GET", "POST"])
@login_required
def blog_new(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user.id != current_user.id:
        return "Access denied.", 403
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:200]
        body  = request.form.get("body", "").strip()
        if not title or not body:
            flash("Title and body are required.", "danger")
            return redirect(url_for("blog_new", username=username))
        entry = JournalEntry(user_id=current_user.id, title=title,
                             body=body, entry_type="blog")
        db.session.add(entry)
        db.session.flush()
        _save_entry_photos(entry, request.files.getlist("photos"))
        db.session.commit()
        flash("Blog post published!", "success")
        return redirect(url_for("blog_view", username=username, entry_id=entry.id))
    return render_template("blog_write.html", user=user, entry=None, mode="new")

@app.route("/blog/<username>/<int:entry_id>")
def blog_view(username, entry_id):
    user  = User.query.filter_by(username=username).first_or_404()
    entry = JournalEntry.query.get_or_404(entry_id)
    if entry.entry_type != "blog" or entry.user_id != user.id:
        return "Not found.", 404
    is_owner = current_user.is_authenticated and current_user.id == user.id
    return render_template("blog_post.html", user=user, entry=entry, is_owner=is_owner)

@app.route("/blog/<username>/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
def blog_edit(username, entry_id):
    user  = User.query.filter_by(username=username).first_or_404()
    entry = JournalEntry.query.get_or_404(entry_id)
    if entry.entry_type != "blog" or entry.user_id != current_user.id:
        return "Access denied.", 403
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:200]
        body  = request.form.get("body", "").strip()
        if not title or not body:
            flash("Title and body are required.", "danger")
            return redirect(url_for("blog_edit", username=username, entry_id=entry_id))
        entry.title = title
        entry.body  = body
        entry.updated_at = datetime.utcnow()
        _save_entry_photos(entry, request.files.getlist("photos"))
        db.session.commit()
        flash("Post updated!", "success")
        return redirect(url_for("blog_view", username=username, entry_id=entry_id))
    return render_template("blog_write.html", user=user, entry=entry, mode="edit")

@app.route("/blog/<username>/<int:entry_id>/delete", methods=["POST"])
@login_required
def blog_delete(username, entry_id):
    user  = User.query.filter_by(username=username).first_or_404()
    entry = JournalEntry.query.get_or_404(entry_id)
    if entry.entry_type != "blog" or entry.user_id != current_user.id:
        return "Access denied.", 403
    for ep in entry.photos:
        try:
            cloudinary.uploader.destroy(ep.public_id)
        except Exception:
            pass
    db.session.delete(entry)
    db.session.commit()
    flash("Post deleted.", "success")
    return redirect(url_for("blog_index", username=username))

@app.route("/entry_photo/<int:photo_id>/delete", methods=["POST"])
@login_required
def entry_photo_delete(photo_id):
    ep    = EntryPhoto.query.get_or_404(photo_id)
    entry = JournalEntry.query.get_or_404(ep.entry_id)
    if entry.user_id != current_user.id:
        return "Access denied.", 403
    try:
        cloudinary.uploader.destroy(ep.public_id)
    except Exception:
        pass
    db.session.delete(ep)
    db.session.commit()
    if entry.entry_type == "diary":
        return redirect(url_for("diary_edit", entry_id=entry.id))
    return redirect(url_for("blog_edit", username=entry.author.username, entry_id=entry.id))

@app.route("/comment/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    profile_username = comment.profile_user.username
    if current_user.id != comment.profile_id and current_user.id != comment.author_id:
        return redirect(url_for("profile", username=profile_username))
    db.session.delete(comment)
    db.session.commit()
    return redirect(url_for("profile", username=profile_username))

# ── The Spot — Public Corner, Marketplace, Events Near Me ─────────────────────

@app.route("/spot")
def spot_index():
    tab = request.args.get("tab", "events")
    if tab not in ("events", "marketplace"):
        tab = "events"
    city, state, zip_code = spot_location_from_request()
    category = request.args.get("category", "")
    now = datetime.utcnow()
    events = []
    listings = []
    if tab == "events":
        q = CornerEvent.query.filter(
            CornerEvent.status == "active",
            CornerEvent.expires_at > now,
            CornerEvent.event_at >= now - timedelta(hours=12),
        )
        q = apply_location_filter(q, CornerEvent, city, state)
        events = q.order_by(
            CornerEvent.is_promoted.desc(),
            CornerEvent.event_at.asc(),
        ).limit(50).all()
    else:
        q = SpotListing.query.filter(
            SpotListing.status == "active",
            SpotListing.expires_at > now,
        )
        if category in MARKETPLACE_CATEGORIES:
            q = q.filter(SpotListing.category == category)
        q = apply_location_filter(q, SpotListing, city, state)
        listings = q.order_by(SpotListing.created_at.desc()).limit(50).all()
    location_label = ", ".join(p for p in [city, state] if p)
    return render_template(
        "spot.html",
        tab=tab,
        events=events,
        listings=listings,
        city=city,
        state=state,
        zip_code=zip_code,
        location_label=location_label,
        category=category,
        marketplace_categories=MARKETPLACE_CATEGORIES,
        us_states=US_STATES,
        qotd=quote_of_the_day(),
        payments_live=spot_payments_live(),
    )


@app.route("/spot/listing/new", methods=["GET", "POST"])
@login_required
def spot_listing_new():
    category = request.args.get("category", request.form.get("category", "for_sale"))
    if category not in MARKETPLACE_CATEGORIES:
        category = "for_sale"
    fee_cents = listing_fee_cents(category)
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:120]
        body = request.form.get("body", "").strip()
        price = request.form.get("price", "").strip()[:40]
        city, state, zip_code = parse_location_fields(
            request.form.get("city", current_user.city),
            request.form.get("state", current_user.state),
            request.form.get("zip_code", current_user.zip_code),
        )
        cat = request.form.get("category", category)
        if cat not in MARKETPLACE_CATEGORIES:
            cat = category
        fee_cents = listing_fee_cents(cat)
        ok, waived = confirm_spot_fee(fee_cents, request.form)
        if not title or not body:
            flash("Title and description are required.", "danger")
        elif not city or not state:
            flash("City and state are required so people near you can find your listing.", "danger")
        elif not ok:
            flash(f"This category requires a {format_fee(fee_cents)} posting fee. Check the box to continue.", "danger")
        else:
            listing = SpotListing(
                user_id=current_user.id,
                category=cat,
                title=title,
                body=body[:5000],
                price=price,
                city=city,
                state=state,
                zip_code=zip_code,
                fee_cents=fee_cents,
                fee_paid=True,
                expires_at=datetime.utcnow() + timedelta(days=LISTING_LIFESPAN_DAYS),
            )
            db.session.add(listing)
            db.session.commit()
            if fee_cents and waived:
                flash(f"Listing posted! {format_fee(fee_cents)} fee waived during beta.", "success")
            elif fee_cents:
                flash(f"Listing posted! {format_fee(fee_cents)} posting fee recorded.", "success")
            else:
                flash("Listing posted — free category, no fee.", "success")
            return redirect(url_for("spot_listing_view", listing_id=listing.id))
    default_city = current_user.city or ""
    default_state = current_user.state or ""
    default_zip = current_user.zip_code or ""
    return render_template(
        "spot_listing_new.html",
        category=category,
        fee_cents=fee_cents,
        marketplace_categories=MARKETPLACE_CATEGORIES,
        default_city=default_city,
        default_state=default_state,
        default_zip=default_zip,
        us_states=US_STATES,
        payments_live=spot_payments_live(),
    )


@app.route("/spot/listing/<int:listing_id>")
def spot_listing_view(listing_id):
    listing = SpotListing.query.get_or_404(listing_id)
    if listing.status != "active" or listing.expires_at <= datetime.utcnow():
        flash("This listing has expired or been removed.", "info")
        return redirect(url_for("spot_index", tab="marketplace"))
    cat_label = MARKETPLACE_CATEGORIES.get(listing.category, {}).get("label", listing.category)
    is_owner = current_user.is_authenticated and current_user.id == listing.user_id
    return render_template(
        "spot_listing_view.html",
        listing=listing,
        cat_label=cat_label,
        is_owner=is_owner,
    )


@app.route("/spot/listing/<int:listing_id>/delete", methods=["POST"])
@login_required
def spot_listing_delete(listing_id):
    listing = SpotListing.query.get_or_404(listing_id)
    if listing.user_id != current_user.id:
        return "Access denied.", 403
    listing.status = "deleted"
    db.session.commit()
    flash("Listing removed.", "info")
    return redirect(url_for("spot_index", tab="marketplace"))


@app.route("/spot/event/new", methods=["GET", "POST"])
@login_required
def spot_event_new():
    promote_fee = EVENT_PROMOTE_FEE_CENTS
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:120]
        body = request.form.get("body", "").strip()
        venue = request.form.get("venue", "").strip()[:120]
        city, state, zip_code = parse_location_fields(
            request.form.get("city", current_user.city),
            request.form.get("state", current_user.state),
            request.form.get("zip_code", current_user.zip_code),
        )
        event_at = parse_event_datetime(
            request.form.get("event_date", ""),
            request.form.get("event_time", ""),
        )
        is_promoted = request.form.get("is_promoted") == "on"
        fee_cents = promote_fee if is_promoted else 0
        ok, waived = confirm_spot_fee(fee_cents, request.form)
        if not title or not body:
            flash("Title and description are required.", "danger")
        elif not city or not state:
            flash("City and state are required for Events Near Me.", "danger")
        elif not event_at:
            flash("Please enter a valid event date and time.", "danger")
        elif not ok:
            flash(f"Promoted events require a {format_fee(fee_cents)} fee. Check the box to continue.", "danger")
        else:
            event = CornerEvent(
                user_id=current_user.id,
                title=title,
                body=body[:5000],
                venue=venue,
                city=city,
                state=state,
                zip_code=zip_code,
                event_at=event_at,
                is_promoted=is_promoted,
                fee_cents=fee_cents,
                fee_paid=True,
                expires_at=event_at + timedelta(days=EVENT_LIFESPAN_DAYS),
            )
            db.session.add(event)
            db.session.commit()
            if fee_cents and waived:
                flash(f"Event posted! {format_fee(fee_cents)} promotion fee waived during beta.", "success")
            elif fee_cents:
                flash(f"Event posted and promoted! {format_fee(fee_cents)} fee recorded.", "success")
            else:
                flash("Event posted on the Public Corner — free.", "success")
            return redirect(url_for("spot_event_view", event_id=event.id))
    return render_template(
        "spot_event_new.html",
        promote_fee=promote_fee,
        default_city=current_user.city or "",
        default_state=current_user.state or "",
        default_zip=current_user.zip_code or "",
        us_states=US_STATES,
        payments_live=spot_payments_live(),
    )


@app.route("/spot/event/<int:event_id>")
def spot_event_view(event_id):
    event = CornerEvent.query.get_or_404(event_id)
    if event.status != "active" or event.expires_at <= datetime.utcnow():
        flash("This event has expired or been removed.", "info")
        return redirect(url_for("spot_index", tab="events"))
    is_owner = current_user.is_authenticated and current_user.id == event.user_id
    return render_template("spot_event_view.html", event=event, is_owner=is_owner)


@app.route("/spot/event/<int:event_id>/delete", methods=["POST"])
@login_required
def spot_event_delete(event_id):
    event = CornerEvent.query.get_or_404(event_id)
    if event.user_id != current_user.id:
        return "Access denied.", 403
    event.status = "deleted"
    db.session.commit()
    flash("Event removed.", "info")
    return redirect(url_for("spot_index", tab="events"))


# ── T026 — Invite routes ──────────────────────────────────────────────────────

@app.route("/invite/create", methods=["POST"])
@login_required
def invite_create():
    existing = Invite.query.filter_by(created_by=current_user.id).order_by(Invite.created_at.asc()).first()
    if existing:
        token = existing.token
    else:
        token = secrets.token_urlsafe(32)
        invite = Invite(token=token, created_by=current_user.id)
        db.session.add(invite)
        db.session.commit()
    link = url_for("invite_landing", token=token, _external=True)
    return jsonify({"link": link})

@app.route("/invite/<token>")
def invite_landing(token):
    invite = Invite.query.filter_by(token=token).first()
    return render_template("invite_landing.html", invite=invite, token=token)

# ── T027 — Feedback routes ────────────────────────────────────────────────────

@app.route("/feedback/new", methods=["GET", "POST"])
def feedback_new():
    if request.method == "POST":
        category = request.form.get("category", "bug")
        if category not in ("bug", "suggestion"):
            category = "bug"
        title = request.form.get("title", "").strip()[:200]
        body = request.form.get("body", "").strip()
        if not title or not body:
            flash("Please fill in all fields.", "danger")
            return render_template("feedback_form.html")
        user_id = current_user.id if current_user.is_authenticated else None
        fb = Feedback(user_id=user_id, category=category, title=title, body=body)
        db.session.add(fb)
        db.session.commit()
        flash("Thanks! Your feedback was submitted.", "success")
        referrer = request.form.get("referrer", "") or url_for("login")
        return redirect(referrer)
    return render_template("feedback_form.html",
                           referrer=request.referrer or "")

@app.route("/admin/feedback")
@login_required
def feedback_admin():
    if current_user.username != "brickface082":
        return "Access denied.", 403
    bugs = Feedback.query.filter_by(category="bug").order_by(Feedback.created_at.desc()).all()
    suggestions = Feedback.query.filter_by(category="suggestion").order_by(Feedback.created_at.desc()).all()
    return render_template("feedback_admin.html", bugs=bugs, suggestions=suggestions)

@app.route("/admin/feedback/<int:fb_id>/review", methods=["POST"])
@login_required
def feedback_review(fb_id):
    if current_user.username != "brickface082":
        return "Access denied.", 403
    fb = Feedback.query.get_or_404(fb_id)
    fb.status = "reviewed" if fb.status == "open" else "open"
    db.session.commit()
    return redirect(url_for("feedback_admin"))

# ── Email updates (opt-in newsletters) ────────────────────────────────────────

@app.route("/updates/opt-in", methods=["POST"])
@login_required
def updates_opt_in():
    set_updates_opt_in(current_user, True)
    db.session.commit()
    flash("You're on the list! We'll email you about new features and reminders.", "success")
    return redirect(request.referrer or url_for("profile", username=current_user.username))


@app.route("/updates/unsubscribe/<token>")
def updates_unsubscribe(token):
    user = User.query.filter_by(updates_unsub_token=token).first()
    if not user:
        flash("This unsubscribe link is invalid or already used.", "danger")
        return redirect(url_for("login"))
    set_updates_opt_in(user, False)
    db.session.commit()
    flash(f"You've been unsubscribed from {SITE_NAME} update emails.", "info")
    if current_user.is_authenticated and current_user.id == user.id:
        return redirect(url_for("edit_profile"))
    return redirect(url_for("login"))


@app.route("/admin/updates", methods=["GET", "POST"])
@login_required
def admin_updates():
    if current_user.username != "brickface082":
        return "Access denied.", 403
    subscriber_count = User.query.filter_by(updates_opt_in=True).count()
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()[:200]
        body = request.form.get("body", "").strip()
        if not subject or not body:
            flash("Subject and message are required.", "danger")
            return render_template("admin_updates.html", subscriber_count=subscriber_count)
        subscribers = User.query.filter_by(updates_opt_in=True).order_by(User.username).all()
        sent, failed = 0, 0
        for user in subscribers:
            try:
                send_update_email(user, subject, body)
                sent += 1
            except Exception:
                failed += 1
        flash(f"Update sent to {sent} subscriber(s)." + (f" {failed} failed." if failed else ""), "success")
        return redirect(url_for("admin_updates"))
    subscribers = (
        User.query.filter_by(updates_opt_in=True)
        .order_by(User.updates_opt_in_at.desc(), User.username)
        .limit(50)
        .all()
    )
    return render_template(
        "admin_updates.html",
        subscriber_count=subscriber_count,
        subscribers=subscribers,
    )


# ── T028 — Delete account ─────────────────────────────────────────────────────

@app.route("/account/delete", methods=["POST"])
@login_required
def account_delete():
    """Multi-step account deletion. Backend verifies username match even if JS is disabled."""
    confirm_username = request.form.get("confirm_username", "").strip()
    if confirm_username != current_user.username:
        flash("Username didn't match. Account was NOT deleted.", "danger")
        return redirect(url_for("edit_profile"))

    uid = current_user.id

    # Delete in FK-safe order — no cascades, explicit SQL (W003: FK constraint prevention)
    # 1. PollVotes cast by this user on other people's polls
    PollVote.query.filter_by(user_id=uid).delete(synchronize_session=False)
    # 2. PollVotes + PollOptions on polls created by this user
    poll_ids = [p.id for p in Poll.query.filter_by(creator_id=uid).with_entities(Poll.id).all()]
    if poll_ids:
        PollVote.query.filter(PollVote.poll_id.in_(poll_ids)).delete(synchronize_session=False)
        PollOption.query.filter(PollOption.poll_id.in_(poll_ids)).delete(synchronize_session=False)
    Poll.query.filter_by(creator_id=uid).delete(synchronize_session=False)
    # 3. EntryPhotos + JournalEntries
    entry_ids = [e.id for e in JournalEntry.query.filter_by(user_id=uid).with_entities(JournalEntry.id).all()]
    if entry_ids:
        EntryPhoto.query.filter(EntryPhoto.entry_id.in_(entry_ids)).delete(synchronize_session=False)
    JournalEntry.query.filter_by(user_id=uid).delete(synchronize_session=False)
    # 4. Photos + PhotoAlbums
    album_ids = [a.id for a in PhotoAlbum.query.filter_by(user_id=uid).with_entities(PhotoAlbum.id).all()]
    if album_ids:
        Photo.query.filter(Photo.album_id.in_(album_ids)).delete(synchronize_session=False)
    PhotoAlbum.query.filter_by(user_id=uid).delete(synchronize_session=False)
    # 5. Comments (authored or on their profile)
    Comment.query.filter(
        (Comment.author_id == uid) | (Comment.profile_id == uid)
    ).delete(synchronize_session=False)
    # 6. Direct messages (sent or received)
    DirectMessage.query.filter(
        (DirectMessage.from_id == uid) | (DirectMessage.to_id == uid)
    ).delete(synchronize_session=False)
    # 7. Crew requests
    CrewRequest.query.filter(
        (CrewRequest.from_id == uid) | (CrewRequest.to_id == uid)
    ).delete(synchronize_session=False)
    # 8. Bulletins + Posts + Spot
    Bulletin.query.filter_by(user_id=uid).delete(synchronize_session=False)
    Post.query.filter_by(user_id=uid).delete(synchronize_session=False)
    SpotListing.query.filter_by(user_id=uid).delete(synchronize_session=False)
    CornerEvent.query.filter_by(user_id=uid).delete(synchronize_session=False)
    UserSound.query.filter_by(user_id=uid).delete(synchronize_session=False)
    montage = PhotoMontage.query.filter_by(user_id=uid).first()
    if montage:
        for slide in montage.slides:
            if slide.source == "upload" and slide.public_id:
                try:
                    cloudinary.uploader.destroy(slide.public_id)
                except Exception:
                    pass
        db.session.delete(montage)
    ProfileView.query.filter(
        (ProfileView.profile_id == uid) | (ProfileView.viewer_id == uid)
    ).delete(synchronize_session=False)
    # 9. Invites and referrals
    invite_ids = [i.id for i in Invite.query.filter_by(created_by=uid).all()]
    if invite_ids:
        InviteReferral.query.filter(InviteReferral.invite_id.in_(invite_ids)).delete(synchronize_session=False)
    InviteReferral.query.filter_by(user_id=uid).delete(synchronize_session=False)
    Invite.query.filter_by(created_by=uid).delete(synchronize_session=False)
    for inv in Invite.query.filter_by(used_by=uid).all():
        inv.used_by = None
        inv.used_at = None
    # 10. Anonymize feedback (keep the report, lose the attribution)
    Feedback.query.filter_by(user_id=uid).update({"user_id": None}, synchronize_session=False)
    # 11. Password reset tokens
    PasswordResetToken.query.filter_by(user_id=uid).delete(synchronize_session=False)
    # 12. Flush all FK children, then delete the user row
    db.session.flush()
    user_obj = db.session.get(User, uid)
    if user_obj:
        delete_profile_song_file(user_obj.profile_song)
    db.session.delete(user_obj)
    db.session.commit()
    logout_user()
    flash("Your account has been permanently deleted.", "info")
    return redirect(url_for("login"))

# ── T029 — Password reset ─────────────────────────────────────────────────────

@app.route("/help")
def help_page():
    return render_template("help.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("profile", username=current_user.username))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = secrets.token_urlsafe(32)
            record = PasswordResetToken(user_id=user.id, token=token)
            db.session.add(record)
            db.session.commit()
            reset_url = url_for("reset_password", token=token, _external=True)
            try:
                msg = Message(
                    f"Reset your {SITE_NAME} password",
                    recipients=[user.email],
                    body=(
                        f"Hi {user.username},\n\n"
                        f"Click the link below to reset your password.\n"
                        f"This link expires in 1 hour and can only be used once.\n\n"
                        f"{reset_url}\n\n"
                        f"If you didn't request this, you can ignore this email."
                    )
                )
                mail.send(msg)
            except Exception:
                pass  # never reveal mail failure — prevents enumeration + avoids 500
        flash("If an account with that email exists, a reset link has been sent.", "info")
        return redirect(url_for("forgot_password"))
    return render_template("forgot_password.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("profile", username=current_user.username))
    record = PasswordResetToken.query.filter_by(token=token, used=False).first()
    if not record or (datetime.utcnow() - record.created_at) > timedelta(hours=1):
        flash("This reset link is invalid or has expired. Request a new one.", "danger")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("reset_password.html", token=token)
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("reset_password.html", token=token)
        # Mark used FIRST (FMEA #3: prevent token reuse on concurrent requests)
        record.used = True
        record.user.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
        db.session.commit()
        flash("Password reset! You can now log in with your new password.", "success")
        return redirect(url_for("login"))
    return render_template("reset_password.html", token=token)

with app.app_context():
    os.makedirs(os.path.join(basedir, "instance"), exist_ok=True)
    db.create_all()
    is_pg = database_url.startswith("postgresql")
    dt_type = "TIMESTAMP" if is_pg else "DATETIME"
    # user table migrations — each column in its own connection (M010: PG aborts whole tx on failure)
    with db.engine.connect() as conn:
        if is_pg:
            existing_user = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_user = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        for col, definition in [
            ("top8", "VARCHAR(200) DEFAULT ''"),
            ("status", "VARCHAR(10) DEFAULT 'online'"),
            ("last_seen", dt_type),
            ("msg_filter", "VARCHAR(10) DEFAULT 'open'"),
            ("away_message", "TEXT DEFAULT ''"),
            ("alert_sound", "VARCHAR(30) DEFAULT 'classic_beep'"),
            ("custom_sound", "TEXT DEFAULT ''"),
        ]:
            if col not in existing_user:
                conn.execute(db.text(f'ALTER TABLE "user" ADD COLUMN {col} {definition}'))
        conn.commit()

    # direct_message migrations — separate connection per D002 SOP
    with db.engine.connect() as conn:
        if is_pg:
            existing_dm = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='direct_message'"
            ))}
        else:
            existing_dm = {row[1] for row in conn.execute(db.text("PRAGMA table_info('direct_message')"))}
        if "is_read" not in existing_dm:
            conn.execute(db.text("ALTER TABLE direct_message ADD COLUMN is_read BOOLEAN DEFAULT FALSE"))
        conn.commit()

    # user profile_views migration — separate connection per D002 SOP
    with db.engine.connect() as conn:
        if is_pg:
            existing_u2 = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_u2 = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "profile_views" not in existing_u2:
            conn.execute(db.text("ALTER TABLE \"user\" ADD COLUMN profile_views INTEGER DEFAULT 0"))
        conn.commit()

    # user mood migration — separate connection per D002 SOP
    with db.engine.connect() as conn:
        if is_pg:
            existing_u3 = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_u3 = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "mood" not in existing_u3:
            conn.execute(db.text("ALTER TABLE \"user\" ADD COLUMN mood VARCHAR(30) DEFAULT ''"))
        conn.commit()

    # T024 — user polls_enabled migration — separate connection per D002 SOP
    with db.engine.connect() as conn:
        if is_pg:
            existing_u4 = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_u4 = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "polls_enabled" not in existing_u4:
            conn.execute(db.text('ALTER TABLE "user" ADD COLUMN polls_enabled BOOLEAN DEFAULT FALSE'))
        conn.commit()

    # font_choice migration — separate connection (M010 SOP) ─────────────────
    with db.engine.connect() as conn:
        if is_pg:
            existing_fc = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_fc = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "font_choice" not in existing_fc:
            conn.execute(db.text("ALTER TABLE \"user\" ADD COLUMN font_choice VARCHAR(50) DEFAULT 'Arial'"))
        conn.commit()

    # dark_mode migration — separate connection (M010 SOP) ───────────────────
    with db.engine.connect() as conn:
        if is_pg:
            existing_dm = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_dm = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "dark_mode" not in existing_dm:
            conn.execute(db.text('ALTER TABLE "user" ADD COLUMN dark_mode BOOLEAN DEFAULT FALSE'))
        conn.commit()

    # theme_color migration — separate connection (M010 SOP) ──────────────────
    with db.engine.connect() as conn:
        if is_pg:
            existing_tc = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_tc = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "theme_color" not in existing_tc:
            conn.execute(db.text("ALTER TABLE \"user\" ADD COLUMN theme_color VARCHAR(7) DEFAULT '#cc44aa'"))
        conn.commit()

    # ideal_meet migration — separate connection (M010 SOP)
    with db.engine.connect() as conn:
        if is_pg:
            existing_im = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_im = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "ideal_meet" not in existing_im:
            conn.execute(db.text("ALTER TABLE \"user\" ADD COLUMN ideal_meet TEXT DEFAULT ''"))
        conn.commit()

    # joined_at migration — separate connection (M010 SOP)
    with db.engine.connect() as conn:
        if is_pg:
            existing_ja = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_ja = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "joined_at" not in existing_ja:
            conn.execute(db.text(f'ALTER TABLE "user" ADD COLUMN joined_at {dt_type}'))
        conn.commit()

    # Backfill joined_at for existing accounts
    with db.engine.connect() as conn:
        conn.execute(db.text(
            'UPDATE "user" SET joined_at = CURRENT_TIMESTAMP WHERE joined_at IS NULL'
        ))
        conn.commit()

    # profile_song migration — separate connection (M010 SOP)
    with db.engine.connect() as conn:
        if is_pg:
            existing_ps = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_ps = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "profile_song" not in existing_ps:
            conn.execute(db.text("ALTER TABLE \"user\" ADD COLUMN profile_song TEXT DEFAULT ''"))
        conn.commit()

    with db.engine.connect() as conn:
        if is_pg:
            existing_pt = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_pt = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "profile_theme" not in existing_pt:
            conn.execute(db.text("ALTER TABLE \"user\" ADD COLUMN profile_theme VARCHAR(30) DEFAULT ''"))
        conn.commit()

    with db.engine.connect() as conn:
        if is_pg:
            existing_cc = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_cc = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "custom_css" not in existing_cc:
            conn.execute(db.text("ALTER TABLE \"user\" ADD COLUMN custom_css TEXT DEFAULT ''"))
        conn.commit()

    # song_autoplay migration — separate connection (M010 SOP)
    with db.engine.connect() as conn:
        if is_pg:
            existing_sa = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_sa = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "song_autoplay" not in existing_sa:
            conn.execute(db.text('ALTER TABLE "user" ADD COLUMN song_autoplay BOOLEAN DEFAULT FALSE'))
        conn.commit()

    # email updates opt-in — separate connection (M010 SOP)
    with db.engine.connect() as conn:
        if is_pg:
            existing_up = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_up = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        for col, definition in [
            ("updates_opt_in", "BOOLEAN DEFAULT FALSE"),
            ("updates_opt_in_at", dt_type),
            ("updates_unsub_token", "VARCHAR(64)"),
        ]:
            if col not in existing_up:
                conn.execute(db.text(f'ALTER TABLE "user" ADD COLUMN {col} {definition}'))
        conn.commit()

    # user location fields — separate connection (M010 SOP)
    with db.engine.connect() as conn:
        if is_pg:
            existing_loc = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_loc = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        for col, definition in [
            ("city", "VARCHAR(80) DEFAULT ''"),
            ("state", "VARCHAR(2) DEFAULT ''"),
            ("zip_code", "VARCHAR(10) DEFAULT ''"),
        ]:
            if col not in existing_loc:
                conn.execute(db.text(f'ALTER TABLE "user" ADD COLUMN {col} {definition}'))
        conn.commit()

    # show_daily_quote — separate connection (M010 SOP)
    with db.engine.connect() as conn:
        if is_pg:
            existing_qd = {row[0] for row in conn.execute(db.text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='user'"
            ))}
        else:
            existing_qd = {row[1] for row in conn.execute(db.text("PRAGMA table_info('user')"))}
        if "show_daily_quote" not in existing_qd:
            conn.execute(db.text('ALTER TABLE "user" ADD COLUMN show_daily_quote BOOLEAN DEFAULT TRUE'))
        conn.commit()
        conn.execute(db.text(
            'UPDATE "user" SET show_daily_quote = TRUE WHERE show_daily_quote IS NULL'
        ))
        conn.commit()

    # spot_listing + corner_event tables (create_all handles fresh DBs)
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)