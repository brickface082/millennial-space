import os
import re
import secrets
from PIL import Image
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, current_user, logout_user, login_required

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
basedir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "instance", "site.db")
app.config["UPLOAD_FOLDER"] = os.path.join(basedir, "static/uploads")

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

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

    def __repr__(self):
        return f"User({self.username})"

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(120), default="")
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref=db.backref("posts", lazy=True, order_by="Post.timestamp.desc()"))

    def __repr__(self):
        return f"Post({self.id}, {self.user_id})"

def extract_url(value):
    value = value.strip()
    match = re.search(r'src=["\']([^"\']+)["\']', value)
    if match:
        return match.group(1)
    return value

def save_picture(form_picture, folder):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    folder_path = os.path.join(app.root_path, "static", "uploads", folder)
    os.makedirs(folder_path, exist_ok=True)
    picture_path = os.path.join(folder_path, picture_fn)
    if folder == "profile_pics":
        output_size = (150, 150)
        i = Image.open(form_picture)
        i.thumbnail(output_size)
        i.save(picture_path)
    else:
        form_picture.save(picture_path)
    return picture_fn

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
    posts = Post.query.filter_by(user_id=user.id).order_by(Post.timestamp.desc()).all()
    return render_template("profile.html", user=user, posts=posts)

@app.route("/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        current_user.bio = request.form.get("bio", "")
        current_user.bg_color = request.form.get("bg_color", "#ff66b2")
        current_user.youtube_url = extract_url(request.form.get("youtube_url", ""))
        current_user.spotify_url = extract_url(request.form.get("spotify_url", ""))
        if request.files.get("profile_pic"):
            pic = request.files["profile_pic"]
            if pic.filename != "":
                current_user.profile_pic = save_picture(pic, "profile_pics")
        if request.files.get("bg_image"):
            bg = request.files["bg_image"]
            if bg.filename != "":
                current_user.bg_image = save_picture(bg, "backgrounds")
        db.session.commit()
        flash("Profile updated!", "success")
        return redirect(url_for("profile", username=current_user.username))
    return render_template("edit_profile.html")

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
            post.image = save_picture(img, "post_images")
    db.session.add(post)
    db.session.commit()
    return redirect(url_for("profile", username=current_user.username))

with app.app_context():
    os.makedirs(os.path.join(basedir, "instance"), exist_ok=True)
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)