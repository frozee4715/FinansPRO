"""Raporlar & Analiz modülü."""
from datetime import date
from flask import Blueprint, render_template, redirect, url_for, request
from .data.repository import get_repo
from .security import login_required

reports_bp = Blueprint("reports", __name__, url_prefix="/raporlar")


@reports_bp.route("/")
@login_required
def index():
    """Raporlar kataloğu → Gösterge Paneline taşındı."""
    qs = request.query_string.decode()
    target = url_for("main.dashboard")
    if qs:
        target += "?" + qs + "#analiz"
    else:
        target += "#analiz"
    return redirect(target, 301)


@reports_bp.route("/bilanco")
@login_required
def bilanco():
    bs = get_repo().balance_sheet()
    return render_template("reports/bilanco.html", bs=bs)


@reports_bp.route("/nakit-akisi")
@login_required
def nakit_akisi():
    forecast = get_repo().cash_flow_forecast(90)
    return render_template("reports/nakit_akisi.html", forecast=forecast)


@reports_bp.route("/karsilastirma")
@login_required
def karsilastirma():
    bugun = date.today()
    yil = int(request.args.get("yil") or bugun.year)
    ay  = int(request.args.get("ay")  or bugun.month)
    data = get_repo().period_comparison(yil, ay)
    return render_template("reports/karsilastirma.html", data=data, yil=yil, ay=ay)


@reports_bp.route("/musteri-karlilik")
@login_required
def musteri_karlilik():
    musteriler = get_repo().customer_profitability(20)
    return render_template("reports/musteri_karlilik.html", musteriler=musteriler)


@reports_bp.route("/denetim-kaydi")
@login_required
def denetim_kaydi():
    logs = get_repo().list_audit_logs(200)
    return render_template("reports/denetim_kaydi.html", logs=logs)
