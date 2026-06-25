# Blueprint name: checks_bp
"""Çek/Senet takip modülü — listele, ekle, düzenle, durum değiştir, sil."""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .data.repository import get_repo
from .security import login_required

checks_bp = Blueprint("checks", __name__, url_prefix="/cek-senet")

TURLER = ["Çek", "Senet"]
DURUMLAR = ["Beklemede", "Tahsil Edildi", "Ödendi", "İade"]


@checks_bp.route("/")
@login_required
def list():
    tur = (request.args.get("tur") or "").strip() or None
    durum = (request.args.get("durum") or "").strip() or None
    cekler = get_repo().list_checks(tur=tur, durum=durum)
    bugun = date.today().isoformat()
    toplam = sum(c.get("tutar") or 0 for c in cekler)
    return render_template("checks/list.html",
                           cekler=cekler,
                           tur=tur or "",
                           durum=durum or "",
                           bugun=bugun,
                           toplam=toplam,
                           TURLER=TURLER,
                           DURUMLAR=DURUMLAR)


@checks_bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        ok, data = _validate(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template("checks/form.html", c=request.form,
                                   mode="create", TURLER=TURLER, DURUMLAR=DURUMLAR)
        get_repo().create_check(**data)
        flash("Çek/Senet kaydedildi. 🧾", "success")
        return redirect(url_for("checks.list"))
    return render_template("checks/form.html",
                           c={"vade_tarihi": date.today().isoformat(), "durum": "Beklemede"},
                           mode="create", TURLER=TURLER, DURUMLAR=DURUMLAR)


@checks_bp.route("/<int:cid>/duzenle", methods=["GET", "POST"])
@login_required
def edit(cid):
    repo = get_repo()
    c = repo.get_check(cid)
    if not c:
        flash("Kayıt bulunamadı.", "danger")
        return redirect(url_for("checks.list"))
    if request.method == "POST":
        ok, data = _validate(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template("checks/form.html", c=request.form,
                                   mode="edit", cid=cid, TURLER=TURLER, DURUMLAR=DURUMLAR)
        repo.update_check(cid, **data)
        flash("Kayıt güncellendi. ✏️", "success")
        return redirect(url_for("checks.list"))
    return render_template("checks/form.html", c=c, mode="edit",
                           cid=cid, TURLER=TURLER, DURUMLAR=DURUMLAR)


@checks_bp.route("/<int:cid>/durum", methods=["POST"])
@login_required
def set_status(cid):
    yeni_durum = (request.form.get("durum") or "").strip()
    if yeni_durum not in DURUMLAR:
        flash("Geçersiz durum değeri.", "danger")
        return redirect(url_for("checks.list"))
    repo = get_repo()
    if not repo.get_check(cid):
        flash("Kayıt bulunamadı.", "danger")
        return redirect(url_for("checks.list"))
    repo.set_check_status(cid, yeni_durum)
    flash(f"Durum «{yeni_durum}» olarak güncellendi.", "success")
    return redirect(url_for("checks.list"))


@checks_bp.route("/<int:cid>/sil", methods=["POST"])
@login_required
def delete(cid):
    get_repo().delete_check(cid)
    flash("Kayıt silindi. 🗑️", "info")
    return redirect(url_for("checks.list"))


def _validate(form):
    hatalar = []
    tur = (form.get("tur") or "").strip()
    taraf = (form.get("taraf") or "").strip()
    vade_tarihi = (form.get("vade_tarihi") or "").strip()
    durum = (form.get("durum") or "Beklemede").strip()
    notlar = (form.get("notlar") or "").strip()

    if tur not in TURLER:
        hatalar.append("Tür seçiniz: Çek veya Senet.")
    if not taraf or len(taraf) > 120:
        hatalar.append("Taraf adı 1-120 karakter olmalı.")
    if not vade_tarihi:
        hatalar.append("Vade tarihi giriniz.")
    if durum not in DURUMLAR:
        hatalar.append("Geçerli bir durum seçiniz.")
    try:
        tutar = float(form.get("tutar") or 0)
        if tutar <= 0:
            hatalar.append("Tutar 0'dan büyük olmalı.")
    except ValueError:
        tutar = 0
        hatalar.append("Tutar geçerli bir sayı olmalı.")

    if hatalar:
        return False, hatalar
    return True, {"tur": tur, "taraf": taraf, "tutar": tutar,
                  "vade_tarihi": vade_tarihi, "durum": durum, "notlar": notlar}
