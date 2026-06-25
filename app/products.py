"""Ürün modülü — listele, ekle, düzenle, sil, ara, stok hareketleri."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .data.repository import get_repo
from .security import login_required

products_bp = Blueprint("products", __name__, url_prefix="/urunler")

KATEGORILER = ["Genel", "Elektronik", "Gıda", "Tekstil", "Hizmet",
               "Yazılım", "Mobilya", "Kırtasiye", "Sarf Malzeme", "Diğer"]


@products_bp.route("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    urunler = get_repo().list_products(q or None)
    return render_template("products/list.html", urunler=urunler, q=q)


@products_bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        ok, data = _validate(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template("products/form.html", urun=request.form, mode="create", kategoriler=KATEGORILER)
        get_repo().create_product(**data)
        flash("Ürün başarıyla eklendi. 📦", "success")
        return redirect(url_for("products.list"))
    return render_template("products/form.html", urun=None, mode="create", kategoriler=KATEGORILER)


@products_bp.route("/<int:pid>/duzenle", methods=["GET", "POST"])
@login_required
def edit(pid):
    repo = get_repo()
    urun = repo.get_product(pid)
    if not urun:
        flash("Ürün bulunamadı.", "danger")
        return redirect(url_for("products.list"))
    if request.method == "POST":
        ok, data = _validate(request.form)
        if not ok:
            for h in data:
                flash(h, "danger")
            return render_template("products/form.html", urun=request.form, mode="edit", pid=pid, kategoriler=KATEGORILER)
        repo.update_product(pid, **data)
        flash("Ürün güncellendi. ✏️", "success")
        return redirect(url_for("products.list"))
    return render_template("products/form.html", urun=urun, mode="edit", pid=pid, kategoriler=KATEGORILER)


@products_bp.route("/<int:pid>/sil", methods=["POST"])
@login_required
def delete(pid):
    if get_repo().delete_product(pid):
        flash("Ürün silindi. 🗑️", "info")
    else:
        flash("Bu ürün fatura kalemlerinde kullanıldığı için silinemez.", "danger")
    return redirect(url_for("products.list"))


@products_bp.route("/<int:pid>/stok", methods=["GET", "POST"])
@login_required
def stok_hareket(pid):
    repo = get_repo()
    urun = repo.get_product(pid)
    if not urun:
        flash("Ürün bulunamadı.", "danger")
        return redirect(url_for("products.list"))
    if request.method == "POST":
        tur = request.form.get("tur", "Giriş")
        try:
            miktar = int(request.form.get("miktar") or 0)
            if miktar <= 0:
                raise ValueError
        except ValueError:
            flash("Miktar geçerli bir pozitif tam sayı olmalı.", "danger")
            return redirect(url_for("products.stok_hareket", pid=pid))
        aciklama = (request.form.get("aciklama") or "").strip()
        repo.add_stock_movement(urun_id=pid, tur=tur, miktar=miktar, aciklama=aciklama)
        flash(f"Stok hareketi kaydedildi: {tur} {miktar} adet.", "success")
        return redirect(url_for("products.stok_hareket", pid=pid))
    hareketler = repo.list_stock_movements(pid)
    return render_template("products/stok.html", urun=urun, hareketler=hareketler)


def _validate(form):
    name = (form.get("name") or "").strip()
    aciklama = (form.get("aciklama") or "").strip()
    kategori = (form.get("kategori") or "Genel").strip()
    hatalar = []
    if not name or len(name) > 50:
        hatalar.append("Ürün adı 1-50 karakter olmalı.")
    if len(aciklama) > 120:
        hatalar.append("Açıklama en fazla 120 karakter olabilir.")
    try:
        birim_fiyat = float(form.get("birim_fiyat") or 0)
        if birim_fiyat < 0:
            hatalar.append("Fiyat negatif olamaz.")
    except ValueError:
        birim_fiyat = 0
        hatalar.append("Fiyat geçerli bir sayı olmalı.")
    try:
        stok = int(form.get("stok") or 0)
        if stok < 0:
            hatalar.append("Stok negatif olamaz.")
    except ValueError:
        stok = 0
        hatalar.append("Stok tam sayı olmalı.")
    if hatalar:
        return False, hatalar
    return True, {"name": name, "aciklama": aciklama,
                  "birim_fiyat": birim_fiyat, "stok": stok, "kategori": kategori}
