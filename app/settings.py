"""Ayarlar modülü — şirket bilgisi, marka rengi, para birimi, KDV."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from .data.repository import get_repo
from .security import admin_required, is_pro
from flask import session

settings_bp = Blueprint("settings", __name__, url_prefix="/ayarlar")

METIN_ALANLAR = [
    "sirket_unvan", "sirket_vergi_no", "sirket_adres",
    "sirket_telefon", "sirket_eposta", "para_birimi",
    "varsayilan_kdv", "marka_renk",
]

KISIEL_ALANLAR = [
    "marka_renk", "ikincil_renk", "yazi_tipi",
    "kose_yuvarlak", "kompakt_mod", "sidebar_genislik",
]


@settings_bp.route("/kisisellestir", methods=["GET", "POST"])
def kisisellestir():
    """Pro kullanıcılar için görsel kişiselleştirme."""
    if not session.get("user_id"):
        flash("Lütfen önce giriş yapın.", "warning")
        return redirect(url_for("auth.login"))
    if not is_pro():
        flash("Bu özellik Pro sürüme özeldir. ✨", "warning")
        return redirect(url_for("billing.upgrade"))

    repo = get_repo()
    if request.method == "POST":
        for alan in KISIEL_ALANLAR:
            repo.set_setting(alan, (request.form.get(alan) or "").strip())
        flash("Kişiselleştirme ayarları kaydedildi. 🎨", "success")
        return redirect(url_for("settings.kisisellestir"))

    s = repo.all_settings()
    for alan in KISIEL_ALANLAR:
        s.setdefault(alan, "")
    return render_template("settings/kisisellestir.html", s=s)


@settings_bp.route("/", methods=["GET", "POST"])
@admin_required
def index():
    repo = get_repo()
    if request.method == "POST":
        for alan in METIN_ALANLAR:
            repo.set_setting(alan, (request.form.get(alan) or "").strip())
        flash("Ayarlar kaydedildi. ✅", "success")
        return redirect(url_for("settings.index"))

    s = repo.all_settings()
    s.setdefault("para_birimi", current_app.config["DEFAULT_CURRENCY"])
    s.setdefault("varsayilan_kdv", current_app.config["DEFAULT_KDV"])
    s.setdefault("marka_renk", "")
    return render_template("settings/index.html", s=s)
