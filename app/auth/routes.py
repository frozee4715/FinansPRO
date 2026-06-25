"""
Kimlik doğrulama rotaları: giriş, kayıt, çıkış.
"""
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app
)

from ..data.repository import get_repo
from ..security import (
    hash_password, verify_password, login_user, logout_user, check_password_strength
)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/giris", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()
        parola = request.form.get("parola") or ""

        repo = get_repo()
        user = repo.get_user_by_login(identifier)

        if not user:
            flash("Böyle bir kullanıcı bulunamadı.", "danger")
            return render_template("auth/login.html", identifier=identifier)

        # Hesap kilitli mi?
        kalan_sn = repo.is_locked(user)
        if kalan_sn > 0:
            dk = max(1, kalan_sn // 60)
            flash(f"Hesabınız geçici olarak kilitli. ~{dk} dakika sonra tekrar deneyin.", "danger")
            return render_template("auth/login.html", identifier=identifier)

        # Pasif hesap
        if not user.get("aktif", 1):
            flash("Hesabınız yönetici tarafından devre dışı bırakılmış.", "danger")
            return render_template("auth/login.html", identifier=identifier)

        # Parola doğru mu?
        if verify_password(user.get("parola_hash"), parola):
            repo.reset_login_state(user["id"])
            login_user(user)
            flash(f"Hoş geldiniz, {user['name']}! 👋", "success")
            return redirect(url_for("main.dashboard"))

        # Yanlış parola → başarısız giriş kaydı + kilit
        kalan = repo.register_failed_login(
            user["id"],
            current_app.config["MAX_LOGIN_ATTEMPTS"],
            current_app.config["LOCKOUT_MINUTES"],
        )
        if kalan > 0:
            flash(f"Şifre hatalı! Kalan deneme hakkınız: {kalan}", "warning")
        else:
            dk = current_app.config["LOCKOUT_MINUTES"]
            flash(f"Çok fazla hatalı deneme. Hesabınız {dk} dakika kilitlendi.", "danger")
        return render_template("auth/login.html", identifier=identifier)

    return render_template("auth/login.html", identifier="")


@auth_bp.route("/kayit", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        eposta = (request.form.get("eposta") or "").strip().lower()
        age_raw = (request.form.get("age") or "").strip()
        parola = request.form.get("parola") or ""
        parola2 = request.form.get("parola2") or ""

        hatalar = []
        if not name or len(name) > 30:
            hatalar.append("İsim 1-30 karakter olmalı.")
        if "@" not in eposta or "." not in eposta:
            hatalar.append("Geçerli bir e-posta giriniz.")
        try:
            age = int(age_raw)
            if not (0 < age < 120):
                hatalar.append("Yaş 1-120 arasında olmalı.")
        except ValueError:
            age = None
            hatalar.append("Yaş sayı olmalı.")
        hatalar.extend(check_password_strength(parola))
        if parola != parola2:
            hatalar.append("Şifreler eşleşmiyor.")

        repo = get_repo()
        if not hatalar and repo.email_exists(eposta):
            hatalar.append("Bu e-posta zaten kayıtlı.")

        if hatalar:
            for h in hatalar:
                flash(h, "danger")
            return render_template("auth/register.html",
                                   name=name, eposta=eposta, age=age_raw)

        repo.create_user(
            name=name, age=age, eposta=eposta,
            parola_hash=hash_password(parola), rol="kullanici",
        )
        flash("Kaydınız oluşturuldu! Şimdi giriş yapabilirsiniz.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", name="", eposta="", age="")


@auth_bp.route("/cikis")
def logout():
    logout_user()
    flash("Çıkış yapıldı. Görüşmek üzere! 👋", "info")
    return redirect(url_for("auth.login"))
