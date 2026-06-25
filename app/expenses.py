"""Gider/masraf modülü — listele, ekle, düzenle, sil."""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .data.repository import get_repo
from .security import login_required

expenses_bp = Blueprint("expenses", __name__, url_prefix="/giderler")

KATEGORILER = ["Kira", "Maaş", "Fatura (Elektrik/Su/İnternet)", "Malzeme",
               "Ulaşım", "Pazarlama", "Vergi/SGK", "Diğer"]


@expenses_bp.route("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    giderler = get_repo().list_expenses(q or None)
    toplam = sum(g.get("tutar") or 0 for g in giderler)
    return render_template("expenses/list.html", giderler=giderler, q=q, toplam=toplam)


@expenses_bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        ok, data = _validate(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template("expenses/form.html", gider=request.form,
                                   mode="create", kategoriler=KATEGORILER)
        get_repo().create_expense(**data)
        flash("Gider kaydedildi. 💸", "success")
        return redirect(url_for("expenses.list"))
    return render_template("expenses/form.html",
                           gider={"tarih": date.today().isoformat()},
                           mode="create", kategoriler=KATEGORILER)


@expenses_bp.route("/<int:eid>/duzenle", methods=["GET", "POST"])
@login_required
def edit(eid):
    repo = get_repo()
    gider = repo.get_expense(eid)
    if not gider:
        flash("Gider bulunamadı.", "danger")
        return redirect(url_for("expenses.list"))
    if request.method == "POST":
        ok, data = _validate(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template("expenses/form.html", gider=request.form,
                                   mode="edit", eid=eid, kategoriler=KATEGORILER)
        repo.update_expense(eid, **data)
        flash("Gider güncellendi. ✏️", "success")
        return redirect(url_for("expenses.list"))
    return render_template("expenses/form.html", gider=gider, mode="edit",
                           eid=eid, kategoriler=KATEGORILER)


@expenses_bp.route("/<int:eid>/sil", methods=["POST"])
@login_required
def delete(eid):
    get_repo().delete_expense(eid)
    flash("Gider silindi. 🗑️", "info")
    return redirect(url_for("expenses.list"))


def _validate(form):
    hatalar = []
    tarih = (form.get("tarih") or "").strip()
    kategori = (form.get("kategori") or "").strip()
    aciklama = (form.get("aciklama") or "").strip()
    odeme_tipi = (form.get("odeme_tipi") or "Nakit").strip()
    if not tarih:
        hatalar.append("Tarih giriniz.")
    if not kategori:
        hatalar.append("Kategori seçiniz.")
    try:
        tutar = float(form.get("tutar") or 0)
        if tutar <= 0:
            hatalar.append("Tutar 0'dan büyük olmalı.")
    except ValueError:
        tutar = 0
        hatalar.append("Tutar geçerli bir sayı olmalı.")
    if hatalar:
        return False, hatalar
    return True, {"tarih": tarih, "kategori": kategori, "aciklama": aciklama,
                  "tutar": tutar, "odeme_tipi": odeme_tipi}
