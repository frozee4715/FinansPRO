# Blueprint name: recurring_bp
"""Tekrarlayan fatura modülü — tanımlama, listeleme, aktif/pasif, manuel çalıştırma."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .data.repository import get_repo
from .security import login_required

recurring_bp = Blueprint("recurring", __name__, url_prefix="/tekrarlayan")

PERIYOTLAR = ["Haftalık", "Aylık", "Yıllık"]


@recurring_bp.route("/")
@login_required
def list():
    kayitlar = get_repo().list_recurring()
    return render_template("recurring/list.html", kayitlar=kayitlar)


@recurring_bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    repo = get_repo()
    musteriler = repo.customer_options()

    if request.method == "POST":
        hatalar = _validate_form(request.form, repo)
        if hatalar:
            for h in hatalar:
                flash(h, "danger")
            return render_template(
                "recurring/form.html",
                musteriler=musteriler,
                periyotlar=PERIYOTLAR,
                form=request.form,
                kayit=None,
            )
        repo.create_recurring(
            musteri_id=int(request.form["musteri_id"]),
            aciklama=(request.form.get("aciklama") or "").strip(),
            tutar=float(request.form.get("tutar") or 0),
            kdv=float(request.form.get("kdv") or 0),
            periyot=(request.form.get("periyot") or "Aylık").strip(),
            sonraki_tarih=(request.form.get("sonraki_tarih") or "").strip(),
        )
        flash("Tekrarlayan fatura tanımı oluşturuldu.", "success")
        return redirect(url_for("recurring.list"))

    if not musteriler:
        flash("Önce en az bir müşteri eklemeniz gerekiyor.", "warning")
    return render_template(
        "recurring/form.html",
        musteriler=musteriler,
        periyotlar=PERIYOTLAR,
        form=None,
        kayit=None,
    )


@recurring_bp.route("/<int:rid>/duzenle", methods=["POST"])
@login_required
def edit(rid):
    repo = get_repo()
    musteriler = repo.customer_options()
    kayit = repo.get_recurring(rid)
    if not kayit:
        flash("Kayıt bulunamadı.", "danger")
        return redirect(url_for("recurring.list"))

    hatalar = _validate_form(request.form, repo)
    if hatalar:
        for h in hatalar:
            flash(h, "danger")
        return render_template(
            "recurring/form.html",
            musteriler=musteriler,
            periyotlar=PERIYOTLAR,
            form=request.form,
            kayit=kayit,
        )

    repo.update_recurring(
        rid,
        musteri_id=int(request.form["musteri_id"]),
        aciklama=(request.form.get("aciklama") or "").strip(),
        tutar=float(request.form.get("tutar") or 0),
        kdv=float(request.form.get("kdv") or 0),
        periyot=(request.form.get("periyot") or "Aylık").strip(),
        sonraki_tarih=(request.form.get("sonraki_tarih") or "").strip(),
    )
    flash("Tekrarlayan fatura güncellendi.", "success")
    return redirect(url_for("recurring.list"))


@recurring_bp.route("/<int:rid>/toggle", methods=["POST"])
@login_required
def toggle(rid):
    repo = get_repo()
    kayit = repo.get_recurring(rid)
    if not kayit:
        flash("Kayıt bulunamadı.", "danger")
        return redirect(url_for("recurring.list"))
    repo.toggle_recurring(rid)
    durum = "pasif" if kayit.get("aktif") else "aktif"
    flash(f"Tekrarlayan fatura {durum} yapıldı.", "info")
    return redirect(url_for("recurring.list"))


@recurring_bp.route("/<int:rid>/simdi-olustur", methods=["POST"])
@login_required
def fire_now(rid):
    repo = get_repo()
    kayit = repo.get_recurring(rid)
    if not kayit:
        flash("Kayıt bulunamadı.", "danger")
        return redirect(url_for("recurring.list"))
    fatura_no = repo.fire_recurring(rid)
    if fatura_no:
        flash(f"Fatura oluşturuldu: {fatura_no}", "success")
    else:
        flash("Fatura oluşturulamadı. Müşteri bilgilerini kontrol edin.", "danger")
    return redirect(url_for("recurring.list"))


@recurring_bp.route("/<int:rid>/sil", methods=["POST"])
@login_required
def delete(rid):
    get_repo().delete_recurring(rid)
    flash("Tekrarlayan fatura tanımı silindi.", "info")
    return redirect(url_for("recurring.list"))


# ============================================================
#  Yardımcı: form doğrulama
# ============================================================

def _validate_form(form, repo):
    hatalar = []
    try:
        musteri_id = int(form.get("musteri_id") or 0)
        if not repo.get_customer(musteri_id):
            hatalar.append("Geçersiz müşteri seçimi.")
    except (TypeError, ValueError):
        hatalar.append("Müşteri seçiniz.")

    try:
        tutar = float(form.get("tutar") or 0)
        if tutar <= 0:
            hatalar.append("Tutar 0'dan büyük olmalı.")
    except ValueError:
        hatalar.append("Tutar geçerli bir sayı olmalı.")

    if not (form.get("sonraki_tarih") or "").strip():
        hatalar.append("Sonraki fatura tarihi giriniz.")

    periyot = (form.get("periyot") or "").strip()
    if periyot not in PERIYOTLAR:
        hatalar.append("Geçersiz periyot seçimi.")

    return hatalar
