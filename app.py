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

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
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
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
        user = User(username=username, email=email, password_hash=hashed_pw)
        db.session.add(user)
        db.session.commit()
        flash("Account created! You can now log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

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
    return render_template("profile.html", user=user, posts=posts, comments=comments,
                           crew_status=crew_status, crew_request_id=crew_request_id,
                           top8_users=top8_users, mood_labels=mood_labels,
                           mood_options=MOOD_OPTIONS)

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
    return render_template("edit_profile.html", mood_options=MOOD_OPTIONS)

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
    return jsonify({
        "count": len(unread),
        "senders": [{"username": u, "count": c} for u, c in by_sender.items()],
        "dnd": (current_user.status == "dnd")
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

if __name__ == "__main__":
    app.run(debug=True)