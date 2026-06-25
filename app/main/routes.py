"""Ana rotalar: açılış, dashboard."""
from flask import Blueprint, render_template, redirect, url_for, session, request

from ..data.repository import get_repo
from ..security import login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@main_bp.route("/panel")
@login_required
def dashboard():
    repo = get_repo()
    start = (request.args.get("start") or "").strip() or None
    end   = (request.args.get("end")   or "").strip() or None

    # Genel sayaçlar
    stats        = repo.dashboard_stats()
    aylik        = repo.monthly_revenue(6)
    top          = repo.top_customers(5)
    son_faturalar = repo.recent_invoices(6)
    uyarilar     = repo.dashboard_alerts()

    # Finansal analiz (tarih filtreli)
    ie           = repo.income_expense(start, end)
    kdv          = repo.kdv_summary(start, end)
    top_urun     = repo.top_products(5, start, end)

    # Alacak & stok (filtreden bağımsız)
    aging        = repo.receivables_aging()
    dusuk_stok   = repo.low_stock_products(5)
    gecikmis_toplam = sum(r["kalan"] for r in aging if (r["gecikme_gun"] or 0) > 0)
    acik_toplam  = sum(r["kalan"] for r in aging)

    # Push bildirimleri: vadesi geçmiş fatura + düşük stok
    try:
        from ..firebase_utils import check_and_notify
        check_and_notify(session["user_id"])
    except Exception:
        pass

    return render_template(
        "dashboard.html",
        stats=stats, aylik=aylik, top=top,
        son_faturalar=son_faturalar, uyarilar=uyarilar,
        start=start or "", end=end or "",
        ie=ie, kdv=kdv, aging=aging,
        top_urun=top_urun, dusuk_stok=dusuk_stok,
        gecikmis_toplam=gecikmis_toplam, acik_toplam=acik_toplam,
    )
