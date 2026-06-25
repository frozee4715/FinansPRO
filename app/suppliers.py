# Blueprint name: suppliers_bp
"""Tedarikçi yönetimi — listele, ekle, düzenle, sil, ara."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .data.repository import get_repo
from .security import login_required

suppliers_bp = Blueprint("suppliers", __name__, url_prefix="/tedarikciler")


@suppliers_bp.route("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    tedarikciler = get_repo().list_suppliers(q or None)
    return render_template("suppliers/list.html", tedarikciler=tedarikciler, q=q)


@suppliers_bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        ok, data = _validate(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template("suppliers/form.html", t=request.form, mode="create")
        get_repo().create_supplier(**data)
        flash("Tedarikçi başarıyla eklendi. 🏭", "success")
        return redirect(url_for("suppliers.list"))
    return render_template("suppliers/form.html", t=None, mode="create")


@suppliers_bp.route("/<int:sid>/duzenle", methods=["GET", "POST"])
@login_required
def edit(sid):
    repo = get_repo()
    t = repo.get_supplier(sid)
    if not t:
        flash("Tedarikçi bulunamadı.", "danger")
        return redirect(url_for("suppliers.list"))
    if request.method == "POST":
        ok, data = _validate(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template("suppliers/form.html", t=request.form, mode="edit", sid=sid)
        repo.update_supplier(sid, **data)
        flash("Tedarikçi güncellendi. ✏️", "success")
        return redirect(url_for("suppliers.list"))
    return render_template("suppliers/form.html", t=t, mode="edit", sid=sid)


@suppliers_bp.route("/<int:sid>/sil", methods=["POST"])
@login_required
def delete(sid):
    get_repo().delete_supplier(sid)
    flash("Tedarikçi silindi. 🗑️", "info")
    return redirect(url_for("suppliers.list"))


def _validate(form):
    unvan = (form.get("unvan") or "").strip()
    vergi_no = (form.get("vergi_no") or "").strip()
    adres = (form.get("adres") or "").strip()
    telefon = (form.get("telefon") or "").strip()
    eposta = (form.get("eposta") or "").strip()
    notlar = (form.get("notlar") or "").strip()
    hatalar = []
    if not unvan or len(unvan) > 120:
        hatalar.append("Ünvan 1-120 karakter olmalı.")
    if vergi_no and (not vergi_no.isdigit() or len(vergi_no) > 11):
        hatalar.append("Vergi/TC no sadece rakam ve en fazla 11 hane olmalı.")
    if eposta and ("@" not in eposta or "." not in eposta):
        hatalar.append("Geçerli bir e-posta adresi giriniz.")
    if hatalar:
        return False, hatalar
    return True, {"unvan": unvan, "vergi_no": vergi_no, "adres": adres,
                  "telefon": telefon, "eposta": eposta, "notlar": notlar}
