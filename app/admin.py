"""Admin paneli — yalnızca yöneticiler. Kullanıcı yönetimi."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from .data.repository import get_repo
from .security import admin_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@admin_required
def users():
    kullanicilar = get_repo().list_users()
    stats = get_repo().dashboard_stats()
    return render_template("admin/users.html", kullanicilar=kullanicilar, stats=stats)


@admin_bp.route("/<int:uid>/rol", methods=["POST"])
@admin_required
def change_role(uid):
    yeni_rol = request.form.get("rol")
    if yeni_rol not in ("admin", "kullanici"):
        flash("Geçersiz rol.", "danger")
        return redirect(url_for("admin.users"))
    if uid == session.get("user_id") and yeni_rol != "admin":
        flash("Kendi yöneticilik yetkinizi kaldıramazsınız.", "warning")
        return redirect(url_for("admin.users"))
    get_repo().update_user_role(uid, yeni_rol)
    flash("Kullanıcı rolü güncellendi. 🛡️", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/<int:uid>/durum", methods=["POST"])
@admin_required
def toggle_active(uid):
    if uid == session.get("user_id"):
        flash("Kendi hesabınızı devre dışı bırakamazsınız.", "warning")
        return redirect(url_for("admin.users"))
    repo = get_repo()
    user = repo.get_user(uid)
    if user:
        repo.set_user_active(uid, not user.get("aktif", 1))
        durum = "aktifleştirildi" if not user.get("aktif", 1) else "devre dışı bırakıldı"
        flash(f"Kullanıcı {durum}.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.route("/<int:uid>/plan", methods=["POST"])
@admin_required
def change_plan(uid):
    repo = get_repo()
    user = repo.get_user(uid)
    if not user:
        flash("Kullanıcı bulunamadı.", "danger")
        return redirect(url_for("admin.users"))
    mevcut = repo.get_user_plan(uid)
    yeni = "free" if mevcut == "pro" else "pro"
    repo.set_user_plan(uid, yeni)
    etiket = "Pro sürüm verildi ✨" if yeni == "pro" else "Pro sürüm geri alındı"
    flash(f"{user['name']}: {etiket}", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/<int:uid>/sil", methods=["POST"])
@admin_required
def delete(uid):
    if uid == session.get("user_id"):
        flash("Kendi hesabınızı silemezsiniz.", "warning")
        return redirect(url_for("admin.users"))
    get_repo().delete_user(uid)
    flash("Kullanıcı silindi. 🗑️", "info")
    return redirect(url_for("admin.users"))
