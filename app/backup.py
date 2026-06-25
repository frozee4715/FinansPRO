"""Otomatik Yedekleme — SQLite yedekleme, imzalama ve geri yükleme (Pro)."""
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, send_file, session, url_for)

from .security import pro_required

backup_bp = Blueprint("backup", __name__, url_prefix="/yedekleme")

BACKUP_DIR_NAME = os.path.join(os.path.dirname(__file__), "data", "backups")

# SQLite application_id — bu uygulamaya özgü 4-byte imza (0x46415050 = "FAPP")
APP_SIG_ID = 0x46415050


# ── Yardımcılar ──────────────────────────────────────────────────────────────

def _backup_dir():
    os.makedirs(BACKUP_DIR_NAME, exist_ok=True)
    return BACKUP_DIR_NAME


def _embed_signature(db_path: str, meta: dict):
    """SQLite başlığına application_id yaz ve _backup_meta tablosu ekle."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"PRAGMA application_id = {APP_SIG_ID}")
        conn.execute("""CREATE TABLE IF NOT EXISTS _backup_meta
                        (anahtar TEXT PRIMARY KEY, deger TEXT)""")
        for k, v in meta.items():
            conn.execute("INSERT OR REPLACE INTO _backup_meta VALUES (?,?)", (k, v))
        conn.commit()
    finally:
        conn.close()


def _verify_signature(db_path: str):
    """
    İmzayı doğrula.
    Başarılı → (meta_dict, None)
    Başarısız → (None, hata_mesajı)
    """
    try:
        conn = sqlite3.connect(db_path)
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        if app_id != APP_SIG_ID:
            conn.close()
            return None, "Bu dosya bu uygulamaya ait bir yedek değil (imza uyuşmuyor)."
        meta = {}
        try:
            rows = conn.execute("SELECT anahtar, deger FROM _backup_meta").fetchall()
            meta = dict(rows)
        except Exception:
            pass
        conn.close()
        return meta, None
    except Exception as e:
        return None, f"Dosya açılamadı: {e}"


def _list_backups():
    d = _backup_dir()
    files = []
    for fname in sorted(os.listdir(d), reverse=True):
        if not fname.endswith(".db"):
            continue
        fpath = os.path.join(d, fname)
        stat = os.stat(fpath)
        meta, _ = _verify_signature(fpath)
        files.append({
            "ad":       fname,
            "boyut":    round(stat.st_size / 1024, 1),
            "tarih":    datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "meta":     meta or {},
            "imzali":   meta is not None,
        })
    return files


# ── Rotalar ──────────────────────────────────────────────────────────────────

@backup_bp.route("/")
@pro_required
def index():
    return render_template("backup/index.html", yedekler=_list_backups())


@backup_bp.route("/olustur", methods=["POST"])
@pro_required
def olustur():
    db_path = current_app.config["SQLITE_PATH"]
    if not os.path.exists(db_path):
        flash("Veritabanı dosyası bulunamadı.", "danger")
        return redirect(url_for("backup.index"))

    zaman = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"yedek_{zaman}.db"
    hedef = os.path.join(_backup_dir(), fname)
    shutil.copy2(db_path, hedef)

    _embed_signature(hedef, {
        "uygulama":  current_app.config.get("APP_NAME", "FakturaApp"),
        "surum":     "1.0",
        "olusturma": datetime.now().isoformat(timespec="seconds"),
        "kullanici": str(session.get("user_id", "")),
    })

    flash(f"Yedek oluşturuldu ve imzalandı: {fname} ✅", "success")
    return redirect(url_for("backup.index"))


@backup_bp.route("/indir/<filename>")
@pro_required
def indir(filename):
    if ".." in filename or "/" in filename or "\\" in filename:
        flash("Geçersiz dosya adı.", "danger")
        return redirect(url_for("backup.index"))
    fpath = os.path.join(_backup_dir(), filename)
    if not os.path.exists(fpath):
        flash("Yedek dosyası bulunamadı.", "danger")
        return redirect(url_for("backup.index"))
    return send_file(fpath, as_attachment=True, download_name=filename)


@backup_bp.route("/geri-yukle", methods=["POST"])
@pro_required
def geri_yukle():
    dosya = request.files.get("yedek_dosya")
    if not dosya or not dosya.filename:
        flash("Dosya seçilmedi.", "danger")
        return redirect(url_for("backup.index"))
    if not dosya.filename.endswith(".db"):
        flash("Sadece .db uzantılı yedek dosyaları kabul edilir.", "danger")
        return redirect(url_for("backup.index"))

    # Geçici konuma kaydet ve imzayı doğrula
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    try:
        os.close(tmp_fd)
        dosya.save(tmp_path)

        meta, hata = _verify_signature(tmp_path)
        if hata:
            flash(f"Geri yükleme reddedildi — {hata}", "danger")
            return redirect(url_for("backup.index"))

        db_path = current_app.config["SQLITE_PATH"]

        # Mevcut DB'yi koruma altına al
        zaman = datetime.now().strftime("%Y%m%d_%H%M%S")
        koruma = os.path.join(_backup_dir(), f"onceki_{zaman}.db")
        if os.path.exists(db_path):
            shutil.copy2(db_path, koruma)
            _embed_signature(koruma, {
                "uygulama":  current_app.config.get("APP_NAME", "FakturaApp"),
                "surum":     "1.0",
                "olusturma": datetime.now().isoformat(timespec="seconds"),
                "not":       "Geri yükleme öncesi otomatik alınan yedek",
            })

        # Geri yükle
        shutil.copy2(tmp_path, db_path)
        app_adi = meta.get("uygulama", "?")
        tarih   = meta.get("olusturma", "?")
        flash(
            f"Veritabanı başarıyla geri yüklendi ✅  "
            f"(Yedek: {app_adi} · {tarih}). "
            f"Önceki hâliniz otomatik yedeklendi: onceki_{zaman}.db",
            "success"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return redirect(url_for("backup.index"))


@backup_bp.route("/sil/<filename>", methods=["POST"])
@pro_required
def sil(filename):
    if ".." in filename or "/" in filename or "\\" in filename:
        flash("Geçersiz dosya adı.", "danger")
        return redirect(url_for("backup.index"))
    fpath = os.path.join(_backup_dir(), filename)
    if os.path.exists(fpath):
        os.remove(fpath)
        flash("Yedek silindi.", "info")
    return redirect(url_for("backup.index"))
