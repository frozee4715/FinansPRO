"""Pro sürüm / plan yönetimi — yükseltme sayfası ve plan değişimi."""
from flask import Blueprint, render_template, redirect, url_for, flash, session
from .data.repository import get_repo
from .security import login_required, admin_required

billing_bp = Blueprint("billing", __name__, url_prefix="/pro")

PRO_FEATURES = [
    {
        "ico": "🤖",
        "ad": "Yapay Zekâ Asistanı",
        "desc": "İşletme verinizi anlayan, soru-cevap yapan ve öneri üreten AI danışman.",
        "url": "ai.chat",
        "admin_only": False,
    },
    {
        "ico": "📊",
        "ad": "Gelişmiş Raporlar",
        "desc": "KDV beyan özeti, gelir/gider, alacak yaşlandırma ve kâr analizleri.",
        "url": "reports.index",
        "admin_only": False,
    },
    {
        "ico": "📄",
        "ad": "Sınırsız PDF & Dışa Aktarma",
        "desc": "Profesyonel fatura çıktıları ve CSV/Excel dışa aktarma.",
        "url": "invoices.list",
        "admin_only": False,
    },
    {
        "ico": "🎨",
        "ad": "Kişiselleştirme",
        "desc": "Şirket logosu, marka rengi ve fatura şablonu özelleştirme.",
        "url": "settings.kisisellestir",
        "admin_only": False,
    },
    {
        "ico": "☁️",
        "ad": "Otomatik Yedekleme",
        "desc": "Verilerinizi düzenli olarak güvenle yedekleyin ve indirin.",
        "url": "backup.index",
        "admin_only": False,
    },
    {
        "ico": "⚡",
        "ad": "Öncelikli Destek",
        "desc": "Sorularınıza öncelikli ve hızlı yanıt, SSS ve talep takibi.",
        "url": "destek.index",
        "admin_only": False,
    },
]


@billing_bp.route("/")
@login_required
def upgrade():
    uid = session.get("user_id")
    plan = get_repo().get_user_plan(uid) if uid else "free"
    return render_template("billing/upgrade.html", plan=plan, features=PRO_FEATURES)


@billing_bp.route("/etkinlestir", methods=["POST"])
@admin_required
def activate():
    uid = session.get("user_id")
    get_repo().set_user_plan(uid, "pro")
    flash("Pro sürüm etkinleştirildi! Tüm özellikler açıldı. ✨", "success")
    return redirect(url_for("billing.upgrade"))


@billing_bp.route("/iptal", methods=["POST"])
@admin_required
def deactivate():
    uid = session.get("user_id")
    get_repo().set_user_plan(uid, "free")
    flash("Pro sürüm devre dışı bırakıldı.", "info")
    return redirect(url_for("billing.upgrade"))
