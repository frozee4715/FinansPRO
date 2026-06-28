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
    # CSRF token'ı giriş anında sabitle: session.clear sonrası ilk render'da
    # üretilmesini bekleme — eşzamanlı isteklerde farklı token üretimi/yarış
    # (ve form↔oturum uyuşmazlığı kaynaklı 403) olasılığını ortadan kaldırır.
    session["_csrf_token"] = secrets.token_hex(32)
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
        # IP allowlist (ADMIN_IP_WHITELIST tanımlıysa)
        if not admin_ip_allowed():
            current_app.logger.warning(
                "Admin paneline izinsiz IP erişimi engellendi: %s", _client_ip()
            )
            abort(403)
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
    """Ortam değişkenlerine göre admin hesabını oluşturur VEYA senkronlar.

    Kimlik bilgileri SADECE ortam değişkenlerinden alınır; sabit/varsayılan
    şifre KULLANILMAZ.

    - ADMIN_EMAIL tanımlı değilse hiçbir şey yapılmaz.
    - O e-postayla admin yoksa oluşturulur (ADMIN_PASSWORD yoksa rastgele
      güçlü şifre üretilir ve bir kez loglanır).
    - Admin ZATEN varsa ve ADMIN_PASSWORD verilmişse, şifre env değeriyle
      SENKRONLANIR (güncellenir), rol 'admin' yapılır, hesap aktifleştirilir
      ve giriş kilidi sıfırlanır. Böylece "Variables'tan şifreyi değiştirdim
      ama giriş yapamıyorum" sorunu ortadan kalkar.

    NOT: Admin şifresi env ile yönetildiğinden, şifreyi uygulama içinden
    değiştirirsen sonraki deploy'da env değerine geri döner. Admin şifresini
    Railway Variables üzerinden yönet.
    """
    import os
    import secrets
    repo = get_repo()
    admin_email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    admin_pass  = os.environ.get("ADMIN_PASSWORD")

    if not admin_email:
        app.logger.info(
            "ADMIN_EMAIL tanımlı değil; admin hesabı oluşturulmadı/senkronlanmadı."
        )
        return

    mevcut = repo.get_user_by_login(admin_email)

    if mevcut:
        # Hesabı admin + aktif yap, kilidi aç
        if mevcut.get("rol") != "admin":
            repo.update_user_role(mevcut["id"], "admin")
        repo.set_user_active(mevcut["id"], True)
        repo.reset_login_state(mevcut["id"])
        if admin_pass:
            repo.set_user_password(mevcut["id"], hash_password(admin_pass))
            app.logger.warning(
                "Admin hesabı (%s) şifresi ortam değişkeniyle SENKRONLANDI.",
                admin_email,
            )
        else:
            app.logger.info(
                "Admin hesabı (%s) mevcut; ADMIN_PASSWORD verilmediği için "
                "şifre değiştirilmedi.", admin_email,
            )
        return

    # Hesap yok → oluştur
    generated = False
    if not admin_pass:
        admin_pass = secrets.token_urlsafe(16)
        generated = True

    repo.create_user(
        name="Admin",
        age=18,
        eposta=admin_email,
        parola_hash=hash_password(admin_pass),
        rol="admin",
    )

    if generated:
        app.logger.warning(
            "Admin hesabı (%s) RASTGELE şifreyle oluşturuldu. "
            "Tek seferlik şifre: %s — hemen giriş yapıp değiştirin "
            "ve ADMIN_PASSWORD ortam değişkenini ayarlayın.",
            admin_email, admin_pass,
        )
    else:
        app.logger.warning(
            "Admin hesabı (%s) ortam değişkenlerindeki şifreyle oluşturuldu.",
            admin_email,
        )


# ----- Admin IP allowlist ---------------------------------------------
def _client_ip():
    """Gerçek istemci IP'si (Railway gibi proxy arkasında X-Forwarded-For)."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or ""


def admin_ip_allowed():
    """ADMIN_IP_WHITELIST boşsa herkese (şifreyle) açık; doluysa yalnızca
    listedeki IP'ler admin paneline erişebilir."""
    import os
    raw = (os.environ.get("ADMIN_IP_WHITELIST") or "").strip()
    if not raw:
        return True
    izinli = {ip.strip() for ip in raw.split(",") if ip.strip()}
    return _client_ip() in izinli
