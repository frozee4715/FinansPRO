"""
Kimlik doğrulama yardımcıları: oturum, dekoratörler, şifre hashleme, CSRF.
"""
import secrets
from functools import wraps
from flask import session, redirect, url_for, flash, g, current_app, request, abort
from werkzeug.security import generate_password_hash, check_password_hash

from .data.repository import get_repo


# ----- CSRF Koruması ---------------------------------------------------
def generate_csrf_token():
    """Her oturuma özgü CSRF token üretir ve session'da saklar."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def validate_csrf():
    """POST/PUT/DELETE isteklerinde CSRF token doğrular. Eşleşmezse 403."""
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    if request.endpoint == "static":
        return
    token = session.get("_csrf_token", "")
    # Form verisi VEYA JSON/AJAX header'ından token kabul et
    form_token = (
        request.form.get("_csrf_token")
        or request.headers.get("X-CSRFToken")
        or request.headers.get("X-Csrf-Token")
        or ""
    )
    if not token or not form_token or not secrets.compare_digest(token, form_token):
        abort(403)


# ----- Şifre -----------------------------------------------------------
def hash_password(plain):
    return generate_password_hash(plain)


def verify_password(parola_hash, plain):
    if not parola_hash:
        return False
    return check_password_hash(parola_hash, plain)


def check_password_strength(parola: str) -> list[str]:
    """Şifre gücünü denetler. Sorun listesi döner (boşsa şifre güçlü)."""
    hatalar = []
    if len(parola) < 8:
        hatalar.append("Şifre en az 8 karakter olmalı.")
    if not any(c.isupper() for c in parola):
        hatalar.append("Şifre en az bir büyük harf içermeli.")
    if not any(c.islower() for c in parola):
        hatalar.append("Şifre en az bir küçük harf içermeli.")
    if not any(c.isdigit() for c in parola):
        hatalar.append("Şifre en az bir rakam içermeli.")
    return hatalar


# ----- Oturum ----------------------------------------------------------
def login_user(user):
    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_role"] = user.get("rol") or "kullanici"
    session.permanent = True


def logout_user():
    session.clear()


def current_user():
    """Giriş yapmış kullanıcıyı (sözlük) döndürür ya da None."""
    if "current_user" in g:
        return g.current_user
    uid = session.get("user_id")
    g.current_user = get_repo().get_user(uid) if uid else None
    return g.current_user


def inject_user():
    """Şablonlara `current_user` değişkenini sağlar."""
    return {"current_user": current_user()}


# ----- Dekoratörler ----------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Lütfen önce giriş yapın.", "warning")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Lütfen önce giriş yapın.", "warning")
            return redirect(url_for("auth.login"))
        if session.get("user_role") != "admin":
            flash("Bu alana yalnızca yöneticiler erişebilir.", "danger")
            return redirect(url_for("main.dashboard"))
        return view(*args, **kwargs)
    return wrapped


# ----- Pro sürüm -------------------------------------------------------
def is_pro():
    """Giriş yapan kullanıcının planının Pro olup olmadığını döndürür."""
    if "is_pro" not in g:
        uid = session.get("user_id")
        if not uid:
            g.is_pro = False
        else:
            g.is_pro = get_repo().get_user_plan(uid) == "pro"
    return g.is_pro


def inject_pro():
    """Şablonlara `is_pro` değişkenini sağlar."""
    return {"is_pro": is_pro()}


def pro_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Lütfen önce giriş yapın.", "warning")
            return redirect(url_for("auth.login"))
        if not is_pro():
            flash("Bu özellik Pro sürüme özeldir. ✨", "warning")
            return redirect(url_for("billing.upgrade"))
        return view(*args, **kwargs)
    return wrapped


# ----- İlk admin tohumu -----------------------------------------------
def seed_admin(app):
    """Web ile giriş yapılabilecek bir admin hesabı yoksa oluşturur."""
    import os
    repo = get_repo()
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@finanspro.com")
    admin_pass  = os.environ.get("ADMIN_PASSWORD", "Admin1234")
    if not repo.email_exists(admin_email):
        repo.create_user(
            name="Admin",
            age=18,
            eposta=admin_email,
            parola_hash=hash_password(admin_pass),
            rol="admin",
        )
        app.logger.warning(
            "Varsayılan admin hesabı oluşturuldu (%s). "
            "Lütfen .env dosyasına ADMIN_EMAIL ve ADMIN_PASSWORD ekleyin "
            "ve ilk girişten sonra şifreyi değiştirin!",
            admin_email,
        )
