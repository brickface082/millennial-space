import os
import re
import secrets
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
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
basedir = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(basedir, "instance", "site.db"))
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["UPLOAD_FOLDER"] = os.path.join(basedir, "static/uploads")

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

# Cloudinary auto-configures from CLOUDINARY_URL env var (set in .env locally, env var on Render)
cloudinary.config()

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
    return dict(image_url=image_url)

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(60), nullable=False)
    bio = db.Column(db.Text, default="")
    profile_pic = db.Column(db.String(120), default="default.jpg")
    bg_color = db.Column(db.String(20), default="#ff66b2")
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

    def __repr__(self):
        return f"User({self.username})"

class CrewRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    to_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending, accepted, blocked
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    from_user = db.relationship("User", foreign_keys=[from_id], backref=db.backref("sent_requests", lazy=True))
    to_user = db.relationship("User", foreign_keys=[to_id], backref=db.backref("received_requests", lazy=True))

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

class Invite(db.Model):
    """T026 — single-use invite tokens. Any user can generate one to bring someone new."""
    __tablename__ = "invite"
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    used_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by],
                              backref=db.backref("invites_sent", lazy=True))
    used_by_user = db.relationship("User", foreign_keys=[used_by],
                                   backref=db.backref("invite_used", uselist=False, lazy=True))

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

def extract_url(value):
    value = value.strip()
    match = re.search(r'src=["\']([^"\']+)["\']', value)
    if match:
        return match.group(1)
    return value

def upload_to_cloudinary(file_obj, folder, resize=None):
    """Upload a file to Cloudinary. Returns (secure_url, public_id).
    resize: optional (w, h) tuple — thumbnail before upload (used for profile pics)."""
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
        user = User(username=username, email=email, password_hash=hashed_pw)
        db.session.add(user)
        db.session.flush()  # get user.id before commit
        if token:
            inv = Invite.query.filter_by(token=token).first()
            if inv and inv.used_by is None:
                inv.used_by = user.id
                inv.used_at = datetime.utcnow()
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
            db.session.commit()
        except Exception:
            db.session.rollback()
    posts = Post.query.filter_by(user_id=user.id).order_by(Post.timestamp.desc()).all()
    comments = Comment.query.filter_by(profile_id=user.id).order_by(Comment.timestamp.desc()).all()
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
    return render_template("profile.html", user=user, posts=posts, comments=comments,
                           crew_status=crew_status, crew_request_id=crew_request_id,
                           top8_users=top8_users, mood_labels=mood_labels,
                           mood_options=MOOD_OPTIONS,
                           recent_photos=recent_photos, album_count=album_count)

@app.route("/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        current_user.bio = request.form.get("bio", "")
        current_user.bg_color = request.form.get("bg_color", "#ff66b2")
        current_user.youtube_url = extract_url(request.form.get("youtube_url", ""))
        current_user.spotify_url = extract_url(request.form.get("spotify_url", ""))
        mf = request.form.get("msg_filter", "open")
        current_user.msg_filter = mf if mf in ("open", "verified", "crew") else "open"
        current_user.away_message = request.form.get("away_message", "")[:200]
        submitted_mood = request.form.get("mood", "")
        current_user.mood = submitted_mood if submitted_mood in VALID_MOODS else ""
        current_user.polls_enabled = request.form.get("polls_enabled") == "on"
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
    return render_template("edit_profile.html", mood_options=MOOD_OPTIONS, invites=invites)

def get_crew_status(current_user_id, profile_user_id):
    req = CrewRequest.query.filter(
        ((CrewRequest.from_id == current_user_id) & (CrewRequest.to_id == profile_user_id)) |
        ((CrewRequest.from_id == profile_user_id) & (CrewRequest.to_id == current_user_id))
    ).first()
    return req

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
    return redirect(url_for("profile", username=current_user.username))

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
    return redirect(url_for("profile", username=username))

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
    q = request.args.get("q", "").strip()[:20]
    results = []
    if q:
        results = User.query.filter(User.username.ilike(f"%{q}%")).limit(20).all()
    return render_template("search.html", q=q, results=results)

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

VALID_SOUNDS = {
    "none", "classic_beep", "double_ping", "triple_beep", "rising_tone",
    "falling_tone", "soft_chime", "retro_game", "soft_pop", "ding",
    "deep_bong", "fast_blip", "old_phone", "doorbell", "laser", "win95", "custom"
}
MAX_CUSTOM_SOUND_B64 = 80_000  # ~60KB audio

@app.route("/sounds", methods=["GET", "POST"])
@login_required
def sounds():
    if request.method == "POST":
        action = request.form.get("action", "select")
        if action == "select":
            s = request.form.get("alert_sound", "classic_beep")
            current_user.alert_sound = s if s in VALID_SOUNDS else "classic_beep"
            db.session.commit()
            flash("Alert sound saved!", "success")
        elif action == "upload":
            f = request.files.get("sound_file")
            if f and f.filename:
                import base64
                data = f.read()
                if len(data) > 60_000:
                    flash("File too large — max 5 seconds / ~60KB.", "danger")
                else:
                    b64 = base64.b64encode(data).decode("utf-8")
                    mime = f.content_type or "audio/mpeg"
                    current_user.custom_sound = f"data:{mime};base64,{b64}"
                    current_user.alert_sound = "custom"
                    db.session.commit()
                    flash("Custom sound uploaded!", "success")
            else:
                flash("No file selected.", "danger")
        elif action == "record":
            b64_data = request.form.get("recorded_sound", "")
            if b64_data and len(b64_data) <= MAX_CUSTOM_SOUND_B64:
                current_user.custom_sound = b64_data
                current_user.alert_sound = "custom"
                db.session.commit()
                flash("Custom recording saved!", "success")
            elif len(b64_data) > MAX_CUSTOM_SOUND_B64:
                flash("Recording too long — max 5 seconds.", "danger")
        return redirect(url_for("sounds"))
    return render_template("sounds.html")

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

# ── T026 — Invite routes ──────────────────────────────────────────────────────

@app.route("/invite/create", methods=["POST"])
@login_required
def invite_create():
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
    # 8. Posts
    Post.query.filter_by(user_id=uid).delete(synchronize_session=False)
    # 9. Invites created by user (delete), used by user (nullify FK)
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
    db.session.delete(user_obj)
    db.session.commit()
    logout_user()
    flash("Your account has been permanently deleted.", "info")
    return redirect(url_for("login"))

# ── T029 — Password reset ─────────────────────────────────────────────────────

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
                    "Reset your Millennial Space password",
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

if __name__ == "__main__":
    app.run(debug=True)