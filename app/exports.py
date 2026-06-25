"""Dışa aktarma modülü — CSV indirme ve yazdırılabilir/PDF fatura görünümü."""
import csv
import io
from flask import Blueprint, Response, render_template, redirect, url_for, flash
from .data.repository import get_repo
from .security import login_required

exports_bp = Blueprint("exports", __name__, url_prefix="/disa-aktar")


def _csv_response(filename, header, rows):
    buf = io.StringIO()
    buf.write("﻿")  # Excel'in Türkçe karakterleri doğru göstermesi için BOM
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@exports_bp.route("/faturalar.csv")
@login_required
def invoices_csv():
    rows = get_repo().list_invoices()
    data = [[r.get("fatura_no"), r.get("musteri_unvan") or "", r.get("tarih") or "",
             r.get("fatura_tipi") or "", f"{r.get('ara_toplam') or 0:.2f}",
             f"{r.get('kdv_tutarı') or 0:.2f}", f"{r.get('toplam_tutar') or 0:.2f}",
             f"{r.get('odenen') or 0:.2f}"] for r in rows]
    return _csv_response("faturalar.csv",
                         ["Fatura No", "Müşteri", "Tarih", "Tip", "Ara Toplam",
                          "KDV", "Genel Toplam", "Ödenen"], data)


@exports_bp.route("/musteriler.csv")
@login_required
def customers_csv():
    rows = get_repo().list_customers()
    data = [[r.get("unvan"), r.get("vergi_no") or "", r.get("telefon") or "",
             r.get("eposta") or "", r.get("adres") or ""] for r in rows]
    return _csv_response("musteriler.csv",
                         ["Ünvan", "Vergi/TC No", "Telefon", "E-posta", "Adres"], data)


@exports_bp.route("/urunler.csv")
@login_required
def products_csv():
    rows = get_repo().list_products()
    data = [[r.get("name"), r.get("aciklama") or "", f"{r.get('birim_fiyat') or 0:.2f}",
             r.get("stok") or 0] for r in rows]
    return _csv_response("urunler.csv",
                         ["Ürün", "Açıklama", "Birim Fiyat", "Stok"], data)


@exports_bp.route("/giderler.csv")
@login_required
def expenses_csv():
    rows = get_repo().list_expenses()
    data = [[r.get("tarih") or "", r.get("kategori") or "", r.get("aciklama") or "",
             f"{r.get('tutar') or 0:.2f}", r.get("odeme_tipi") or ""] for r in rows]
    return _csv_response("giderler.csv",
                         ["Tarih", "Kategori", "Açıklama", "Tutar", "Ödeme Tipi"], data)


@exports_bp.route("/muhasebe.csv")
@login_required
def muhasebe_csv():
    """Logo/Mikro/LUCA uyumlu muhasebe dışa aktarma (gelir + gider + ödemeler)."""
    repo = get_repo()
    rows = []
    for inv in repo.list_invoices():
        rows.append([
            inv.get("tarih") or "", "Fatura",
            inv.get("fatura_no") or "", inv.get("musteri_unvan") or "",
            inv.get("fatura_tipi") or "",
            f"{inv.get('ara_toplam') or 0:.2f}",
            f"{inv.get('kdv_tutarı') or 0:.2f}",
            f"{inv.get('toplam_tutar') or 0:.2f}", "",
        ])
    for pay in repo.list_payments():
        rows.append([
            pay.get("odeme_tarihi") or "", "Ödeme",
            pay.get("fatura_no") or "", pay.get("musteri_unvan") or "",
            pay.get("odeme_tipi") or "", "", "", "",
            f"{pay.get('tutar') or 0:.2f}",
        ])
    for exp in repo.list_expenses():
        rows.append([
            exp.get("tarih") or "", "Gider", "",
            exp.get("kategori") or "", exp.get("aciklama") or "",
            f"{exp.get('tutar') or 0:.2f}", "", "", "",
        ])
    rows.sort(key=lambda r: r[0])
    return _csv_response(
        "muhasebe_export.csv",
        ["Tarih", "Tür", "Referans No", "Taraf", "Açıklama/Tip",
         "Tutar", "KDV", "Toplam", "Ödeme"],
        rows,
    )


@exports_bp.route("/tedarikciler.csv")
@login_required
def suppliers_csv():
    rows = get_repo().list_suppliers()
    data = [[r.get("unvan"), r.get("vergi_no") or "", r.get("telefon") or "",
             r.get("eposta") or "", r.get("adres") or ""] for r in rows]
    return _csv_response("tedarikciler.csv",
                         ["Ünvan", "Vergi No", "Telefon", "E-posta", "Adres"], data)


@exports_bp.route("/fatura/<int:iid>/yazdir")
@login_required
def invoice_print(iid):
    repo = get_repo()
    fatura = repo.get_invoice(iid)
    if not fatura:
        flash("Fatura bulunamadı.", "danger")
        return redirect(url_for("invoices.list"))
    odenen = sum(p["tutar"] for p in repo.list_payments() if p["fatura_id"] == iid)
    sirket = repo.all_settings()
    return render_template("invoices/print.html", f=fatura, odenen=odenen, sirket=sirket)
