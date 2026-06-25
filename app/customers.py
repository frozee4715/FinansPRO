"""Müşteri modülü — listele, ekle, düzenle, sil, ara."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .data.repository import get_repo
from .security import login_required

customers_bp = Blueprint("customers", __name__, url_prefix="/musteriler")


@customers_bp.route("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    musteriler = get_repo().list_customers(q or None)
    return render_template("customers/list.html", musteriler=musteriler, q=q)


@customers_bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        ok, data = _validate(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template("customers/form.html", musteri=request.form, mode="create")
        get_repo().create_customer(**data)
        flash("Müşteri başarıyla eklendi. 🤝", "success")
        return redirect(url_for("customers.list"))
    return render_template("customers/form.html", musteri=None, mode="create")


@customers_bp.route("/<int:cid>/duzenle", methods=["GET", "POST"])
@login_required
def edit(cid):
    repo = get_repo()
    musteri = repo.get_customer(cid)
    if not musteri:
        flash("Müşteri bulunamadı.", "danger")
        return redirect(url_for("customers.list"))
    if request.method == "POST":
        ok, data = _validate(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template("customers/form.html", musteri=request.form, mode="edit", cid=cid)
        repo.update_customer(cid, **data)
        flash("Müşteri güncellendi. ✏️", "success")
        return redirect(url_for("customers.list"))
    return render_template("customers/form.html", musteri=musteri, mode="edit", cid=cid)


@customers_bp.route("/<int:cid>/ekstre")
@login_required
def statement(cid):
    repo = get_repo()
    musteri = repo.get_customer(cid)
    if not musteri:
        flash("Müşteri bulunamadı.", "danger")
        return redirect(url_for("customers.list"))
    hareketler = repo.customer_statement(cid)
    bakiye = hareketler[-1]["bakiye"] if hareketler else 0
    return render_template("customers/statement.html",
                           musteri=musteri, hareketler=hareketler, bakiye=bakiye)


@customers_bp.route("/<int:cid>/sil", methods=["POST"])
@login_required
def delete(cid):
    if get_repo().delete_customer(cid):
        flash("Müşteri silindi. 🗑️", "info")
    else:
        flash("Bu müşteriye ait faturalar olduğu için silinemez. Önce faturalarını silin.", "danger")
    return redirect(url_for("customers.list"))


def _validate(form):
    unvan = (form.get("unvan") or "").strip()
    vergi_no = (form.get("vergi_no") or "").strip()
    adres = (form.get("adres") or "").strip()
    telefon = (form.get("telefon") or "").strip()
    eposta = (form.get("eposta") or "").strip()
    hatalar = []
    if not unvan or len(unvan) > 60:
        hatalar.append("Ünvan 1-60 karakter olmalı.")
    if vergi_no and (not vergi_no.isdigit() or len(vergi_no) > 11):
        hatalar.append("Vergi/TC no sadece rakam ve en fazla 11 hane olmalı.")
    if eposta and ("@" not in eposta or "." not in eposta):
        hatalar.append("Geçerli bir e-posta giriniz.")
    if hatalar:
        return False, hatalar
    return True, {"unvan": unvan, "vergi_no": vergi_no, "adres": adres,
                  "telefon": telefon, "eposta": eposta}
