"""Small social network API and static frontend server."""

from __future__ import annotations

import io
import os
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from uuid import uuid4

import boto3
import click
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from PIL import Image, UnidentifiedImageError
from sqlalchemy import UniqueConstraint, func, select
from werkzeug.security import check_password_hash, generate_password_hash


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "frontend"
load_dotenv(ROOT / ".env")

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    text = db.Column(db.Text, nullable=False, default="")
    image_key = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    author = db.relationship("User")


class Like(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "post_id", name="uq_like_user_post"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id", ondelete="CASCADE"), nullable=False, index=True)


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id", ondelete="CASCADE"), nullable=False, index=True)
    text = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    author = db.relationship("User")


def error(message: str, status: int):
    return jsonify({"error": message}), status


def user_data(user: User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email}


def iso_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(FRONTEND), static_url_path="")
    app.config.update(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        S3_BUCKET=os.getenv("S3_BUCKET"),
        S3_REGION=os.getenv("S3_REGION", "us-east-1"),
        S3_ENDPOINT_URL=os.getenv("S3_ENDPOINT_URL") or None,
    )
    if test_config:
        app.config.update(test_config)
    for key in ("SECRET_KEY", "SQLALCHEMY_DATABASE_URI", "S3_BUCKET"):
        if not app.config[key]:
            raise RuntimeError(f"Missing configuration: {key}")
    if app.config["SECRET_KEY"] == "replace-with-a-long-random-value":
        raise RuntimeError("Set a unique FLASK_SECRET_KEY in backend/.env")

    db.init_app(app)
    s3 = boto3.client(
        "s3",
        region_name=app.config["S3_REGION"],
        endpoint_url=app.config["S3_ENDPOINT_URL"],
        config=Config(s3={"addressing_style": "path"} if app.config["S3_ENDPOINT_URL"] else {}),
    )

    def current_user() -> User | None:
        user_id = session.get("user_id")
        return db.session.get(User, user_id) if user_id else None

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user():
                return error("Сначала войдите в аккаунт", 401)
            return view(*args, **kwargs)

        return wrapped

    def image_url(key: str | None) -> str | None:
        if not key:
            return None
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": app.config["S3_BUCKET"], "Key": key},
            ExpiresIn=3600,
        )

    def post_data(post: Post, viewer_id: int | None) -> dict:
        likes = db.session.scalar(select(func.count()).select_from(Like).where(Like.post_id == post.id))
        liked = bool(viewer_id and db.session.scalar(
            select(Like.id).where(Like.post_id == post.id, Like.user_id == viewer_id)
        ))
        comments = db.session.scalars(
            select(Comment).where(Comment.post_id == post.id).order_by(Comment.created_at.asc(), Comment.id.asc())
        ).all()
        return {
            "id": post.id,
            "author": {"id": post.author.id, "name": post.author.name},
            "text": post.text,
            "image_url": image_url(post.image_key),
            "created_at": iso_time(post.created_at),
            "likes_count": likes,
            "liked": liked,
            "comments": [
                {"id": c.id, "author": {"id": c.author.id, "name": c.author.name}, "text": c.text,
                 "created_at": iso_time(c.created_at)}
                for c in comments
            ],
        }

    @app.before_request
    def check_origin():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                return error("Недопустимый источник запроса", 403)

    @app.errorhandler(413)
    def too_large(_exc):
        return error("Файл слишком большой (до 5 МБ)", 413)

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/api/health")
    def health():
        db.session.execute(select(1))
        return {"status": "ok"}

    @app.get("/api/me")
    def me():
        user = current_user()
        return {"user": user_data(user) if user else None}

    @app.post("/api/register")
    def register():
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        if not 2 <= len(name) <= 60:
            return error("Имя должно содержать от 2 до 60 символов", 400)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
            return error("Укажите корректную почту", 400)
        if len(password) < 8:
            return error("Пароль должен содержать не менее 8 символов", 400)
        if db.session.scalar(select(User.id).where(User.email == email)):
            return error("Эта почта уже зарегистрирована", 409)
        user = User(name=name, email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        session.clear()
        session["user_id"] = user.id
        return {"user": user_data(user)}, 201

    @app.post("/api/login")
    def login():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        user = db.session.scalar(select(User).where(User.email == email))
        if not user or not check_password_hash(user.password_hash, str(data.get("password", ""))):
            return error("Неверная почта или пароль", 401)
        session.clear()
        session["user_id"] = user.id
        return {"user": user_data(user)}

    @app.post("/api/logout")
    def logout():
        session.clear()
        return {"ok": True}

    @app.get("/api/posts")
    def list_posts():
        user = current_user()
        query = select(Post).order_by(Post.created_at.desc(), Post.id.desc()).limit(50)
        if request.args.get("scope") == "mine":
            if not user:
                return error("Сначала войдите в аккаунт", 401)
            query = query.where(Post.user_id == user.id)
        posts = db.session.scalars(query).all()
        return {"posts": [post_data(post, user.id if user else None) for post in posts]}

    @app.post("/api/posts")
    @login_required
    def create_post():
        text = request.form.get("text", "").strip()
        upload = request.files.get("image")
        if len(text) > 2000:
            return error("Текст поста слишком длинный (до 2000 символов)", 400)
        if not text and not upload:
            return error("Напишите текст или добавьте фото", 400)

        image_key = None
        if upload:
            content = upload.read(5 * 1024 * 1024 + 1)
            if len(content) > 5 * 1024 * 1024:
                return error("Файл слишком большой (до 5 МБ)", 413)
            try:
                with Image.open(io.BytesIO(content)) as img:
                    image_format = img.format
                    img.verify()
            except (UnidentifiedImageError, OSError, ValueError):
                return error("Поддерживаются только JPEG, PNG и WebP", 400)
            types = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}
            if image_format not in types:
                return error("Поддерживаются только JPEG, PNG и WebP", 400)
            extension, content_type = types[image_format]
            image_key = f"posts/{uuid4().hex}.{extension}"
            try:
                s3.put_object(Bucket=app.config["S3_BUCKET"], Key=image_key, Body=content, ContentType=content_type)
            except (BotoCoreError, ClientError):
                app.logger.exception("S3 upload failed")
                return error("Не удалось загрузить фото", 502)

        post = Post(user_id=current_user().id, text=text, image_key=image_key)
        db.session.add(post)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            if image_key:
                try:
                    s3.delete_object(Bucket=app.config["S3_BUCKET"], Key=image_key)
                except (BotoCoreError, ClientError):
                    app.logger.exception("Could not clean up orphaned image")
            raise
        return {"post": post_data(post, current_user().id)}, 201

    @app.post("/api/posts/<int:post_id>/like")
    @login_required
    def toggle_like(post_id: int):
        post = db.session.get(Post, post_id)
        if not post:
            return error("Пост не найден", 404)
        user_id = current_user().id
        existing = db.session.scalar(select(Like).where(Like.user_id == user_id, Like.post_id == post_id))
        if existing:
            db.session.delete(existing)
        else:
            db.session.add(Like(user_id=user_id, post_id=post_id))
        db.session.commit()
        return {"post": post_data(post, user_id)}

    @app.post("/api/posts/<int:post_id>/comments")
    @login_required
    def add_comment(post_id: int):
        post = db.session.get(Post, post_id)
        if not post:
            return error("Пост не найден", 404)
        data = request.get_json(silent=True) or {}
        text = str(data.get("text", "")).strip()
        if not 1 <= len(text) <= 1000:
            return error("Комментарий должен содержать от 1 до 1000 символов", 400)
        db.session.add(Comment(user_id=current_user().id, post_id=post_id, text=text))
        db.session.commit()
        return {"post": post_data(post, current_user().id)}, 201

    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        click.echo("Database tables created")

    @app.cli.command("init-local-s3")
    def init_local_s3():
        if not app.config["S3_ENDPOINT_URL"]:
            raise click.ClickException("This command is only for a local S3 endpoint")
        bucket = app.config["S3_BUCKET"]
        try:
            s3.head_bucket(Bucket=bucket)
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
                raise
            s3.create_bucket(Bucket=bucket)
        click.echo(f"S3 bucket ready: {bucket}")

    @app.cli.command("seed-demo")
    def seed_demo():
        if db.session.scalar(select(Post.id).limit(1)):
            click.echo("Posts already exist; nothing added")
            return
        demo_key = "demo/karelia.png"
        s3.put_object(
            Bucket=app.config["S3_BUCKET"], Key=demo_key,
            Body=(ROOT / "demo-photo.png").read_bytes(), ContentType="image/png",
        )
        samples = [
            ("Михаил Соколов", "mikhail@example.test", "Выходные в Карелии. Тишина, сосны, вода и воздух, после которого действительно легче дышать. Иногда это именно то, что нужно."),
            ("Елена Ковалёва", "elena@example.test", "Сегодня был тот самый день, когда всё сложилось. Утренний кофе, длинная прогулка по городу, интересный разговор и ощущение, что впереди — хорошее. Такие простые вещи, а сколько в них смысла."),
        ]
        for name, email, body in samples:
            user = User(name=name, email=email, password_hash=generate_password_hash(uuid4().hex))
            db.session.add(user)
            db.session.flush()
            db.session.add(Post(
                user_id=user.id, text=body,
                image_key=demo_key if email == "mikhail@example.test" else None,
                created_at=datetime.now(timezone.utc) - timedelta(days=1) if email == "mikhail@example.test" else datetime.now(timezone.utc),
            ))
        db.session.commit()
        click.echo("Two demo posts created")

    return app


app = create_app()
