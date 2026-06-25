"""Ödeme modülü — listele, kaydet, sil."""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from .data.repository import get_repo
from .security import login_required

payments_bp = Blueprint("payments", __name__, url_prefix="/odemeler")


@payments_bp.route("/")
@login_required
def list():
    odemeler = get_repo().list_payments()
    return render_template("payments/list.html", odemeler=odemeler)


@payments_bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    repo = get_repo()
    faturalar = repo.invoice_options()

    if request.method == "POST":
        hatalar = []
        try:
            fatura_id = int(request.form.get("fatura_id"))
            if not repo.get_invoice(fatura_id):
                hatalar.append("Geçersiz fatura.")
        except (TypeError, ValueError):
            fatura_id = None
            hatalar.append("Fatura seçiniz.")
        try:
            tutar = float(request.form.get("tutar") or 0)
            if tutar <= 0:
                hatalar.append("Tutar 0'dan büyük olmalı.")
        except ValueError:
            tutar = 0
            hatalar.append("Tutar geçerli bir sayı olmalı.")
        odeme_tarihi = (request.form.get("odeme_tarihi") or "").strip()
        odeme_tipi = (request.form.get("odeme_tipi") or "Nakit").strip()
        if not odeme_tarihi:
            hatalar.append("Ödeme tarihi giriniz.")

        if hatalar:
            for h in hatalar:
                flash(h, "danger")
            return render_template("payments/form.html", faturalar=faturalar,
                                   form=request.form, bugun=date.today().isoformat())

        repo.create_payment(fatura_id=fatura_id, odeme_tarihi=odeme_tarihi,
                            tutar=tutar, odeme_tipi=odeme_tipi)
        flash("Ödeme kaydedildi. 💳", "success")

        # Push bildirimi: ödeme alındı
        try:
            from .firebase_utils import notify_payment_received
            fatura = repo.get_invoice(fatura_id)
            musteri = (fatura or {}).get("unvan") or (fatura or {}).get("musteri", "Müşteri")
            notify_payment_received(session["user_id"], musteri, tutar, fatura_id)
        except Exception:
            pass

        return redirect(url_for("payments.list"))

    if not faturalar:
        flash("Ödeme kaydetmek için önce fatura oluşturun.", "warning")
    return render_template("payments/form.html", faturalar=faturalar,
                           form=None, bugun=date.today().isoformat())


@payments_bp.route("/<int:pid>/sil", methods=["POST"])
@login_required
def delete(pid):
    get_repo().delete_payment(pid)
    flash("Ödeme silindi. 🗑️", "info")
    return redirect(url_for("payments.list"))
