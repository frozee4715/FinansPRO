# Blueprint name: accounts_bp
"""Kasa/Banka Hesapları modülü — hesap yönetimi ve hareket takibi."""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .data.repository import get_repo
from .security import login_required

accounts_bp = Blueprint("accounts", __name__, url_prefix="/hesaplar")

HESAP_TURLERI = ["Kasa", "Banka", "Kredi Kartı", "Diğer"]
HAREKET_TIPLERI = ["Giriş", "Çıkış", "Virman"]
PARA_BIRIMLERI = ["₺", "$", "€", "£"]


@accounts_bp.route("/")
@login_required
def list():
    repo = get_repo()
    hesaplar = repo.list_accounts()
    # Toplam varlık, kasa toplamı, banka toplamı
    toplam_varlik = sum(h.get("bakiye") or 0 for h in hesaplar)
    kasa_toplam = sum(h.get("bakiye") or 0 for h in hesaplar if h.get("tur") == "Kasa")
    banka_toplam = sum(h.get("bakiye") or 0 for h in hesaplar if h.get("tur") == "Banka")
    return render_template(
        "accounts/list.html",
        hesaplar=hesaplar,
        toplam_varlik=toplam_varlik,
        kasa_toplam=kasa_toplam,
        banka_toplam=banka_toplam,
    )


@accounts_bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        ok, data = _validate_account(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template(
                "accounts/form.html",
                hesap=request.form,
                mode="create",
                hesap_turleri=HESAP_TURLERI,
                para_birimleri=PARA_BIRIMLERI,
            )
        get_repo().create_account(**data)
        flash("Hesap oluşturuldu. 🏦", "success")
        return redirect(url_for("accounts.list"))
    return render_template(
        "accounts/form.html",
        hesap={"para_birimi": "₺", "bakiye_baslangic": 0},
        mode="create",
        hesap_turleri=HESAP_TURLERI,
        para_birimleri=PARA_BIRIMLERI,
    )


@accounts_bp.route("/<int:aid>/duzenle", methods=["GET", "POST"])
@login_required
def edit(aid):
    repo = get_repo()
    hesap = repo.get_account(aid)
    if not hesap:
        flash("Hesap bulunamadı.", "danger")
        return redirect(url_for("accounts.list"))
    if request.method == "POST":
        ok, data = _validate_account_edit(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template(
                "accounts/form.html",
                hesap=request.form,
                mode="edit",
                aid=aid,
                hesap_turleri=HESAP_TURLERI,
                para_birimleri=PARA_BIRIMLERI,
            )
        repo.update_account(aid, **data)
        flash("Hesap güncellendi. ✏️", "success")
        return redirect(url_for("accounts.list"))
    return render_template(
        "accounts/form.html",
        hesap=hesap,
        mode="edit",
        aid=aid,
        hesap_turleri=HESAP_TURLERI,
        para_birimleri=PARA_BIRIMLERI,
    )


@accounts_bp.route("/<int:aid>")
@login_required
def detail(aid):
    repo = get_repo()
    hesap = repo.get_account(aid)
    if not hesap:
        flash("Hesap bulunamadı.", "danger")
        return redirect(url_for("accounts.list"))
    hareketler = repo.list_account_movements(aid)
    bakiye = repo.account_balance(aid)
    return render_template(
        "accounts/detail.html",
        hesap=hesap,
        hareketler=hareketler,
        bakiye=bakiye,
        hareket_tipleri=HAREKET_TIPLERI,
    )


@accounts_bp.route("/<int:aid>/hareket", methods=["GET", "POST"])
@login_required
def add_movement(aid):
    repo = get_repo()
    hesap = repo.get_account(aid)
    if not hesap:
        flash("Hesap bulunamadı.", "danger")
        return redirect(url_for("accounts.list"))
    if request.method == "POST":
        ok, data = _validate_movement(request.form, aid)
        if not ok:
            for h in data:
                flash(h, "danger")
            return redirect(url_for("accounts.detail", aid=aid))
        repo.add_movement(**data)
        flash("Hareket eklendi. 💰", "success")
        return redirect(url_for("accounts.detail", aid=aid))
    # GET: yeni hareket formu sayfası olarak detaya yönlendir
    return redirect(url_for("accounts.detail", aid=aid))


@accounts_bp.route("/<int:aid>/sil", methods=["POST"])
@login_required
def delete(aid):
    get_repo().delete_account(aid)
    flash("Hesap silindi. 🗑️", "info")
    return redirect(url_for("accounts.list"))


# ---------------------------------------------------------------------------
# Yardımcı doğrulama fonksiyonları
# ---------------------------------------------------------------------------

def _validate_account(form):
    hatalar = []
    ad = (form.get("ad") or "").strip()
    tur = (form.get("tur") or "").strip()
    para_birimi = (form.get("para_birimi") or "₺").strip()
    aciklama = (form.get("aciklama") or "").strip()
    if not ad:
        hatalar.append("Hesap adı giriniz.")
    if not tur or tur not in HESAP_TURLERI:
        hatalar.append("Geçerli bir hesap türü seçiniz.")
    try:
        bakiye_baslangic = float(form.get("bakiye_baslangic") or 0)
    except ValueError:
        bakiye_baslangic = 0
        hatalar.append("Başlangıç bakiyesi geçerli bir sayı olmalı.")
    if hatalar:
        return False, hatalar
    return True, {
        "ad": ad,
        "tur": tur,
        "para_birimi": para_birimi,
        "bakiye_baslangic": bakiye_baslangic,
        "aciklama": aciklama,
    }


def _validate_account_edit(form):
    hatalar = []
    ad = (form.get("ad") or "").strip()
    tur = (form.get("tur") or "").strip()
    aciklama = (form.get("aciklama") or "").strip()
    if not ad:
        hatalar.append("Hesap adı giriniz.")
    if not tur or tur not in HESAP_TURLERI:
        hatalar.append("Geçerli bir hesap türü seçiniz.")
    if hatalar:
        return False, hatalar
    return True, {"ad": ad, "tur": tur, "aciklama": aciklama}


def _validate_movement(form, hesap_id):
    hatalar = []
    tarih = (form.get("tarih") or "").strip()
    aciklama = (form.get("aciklama") or "").strip()
    tip = (form.get("tip") or "").strip()
    referans = (form.get("referans") or "").strip()
    if not tarih:
        hatalar.append("Tarih giriniz.")
    if not tip or tip not in HAREKET_TIPLERI:
        hatalar.append("Geçerli bir hareket tipi seçiniz.")
    try:
        tutar_raw = float(form.get("tutar") or 0)
        if tutar_raw == 0:
            hatalar.append("Tutar 0 olamaz.")
        # Çıkış tipi için tutarı negatif yap
        if tip == "Çıkış":
            tutar = -abs(tutar_raw)
        else:
            tutar = abs(tutar_raw)
    except ValueError:
        tutar = 0
        hatalar.append("Tutar geçerli bir sayı olmalı.")
    if hatalar:
        return False, hatalar
    return True, {
        "hesap_id": hesap_id,
        "tarih": tarih,
        "aciklama": aciklama,
        "tutar": tutar,
        "tip": tip,
        "referans": referans,
    }
