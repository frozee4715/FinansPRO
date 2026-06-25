"""Öncelikli Destek — Pro kullanıcı destek talep sistemi."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from .data.repository import get_repo
from .security import login_required, pro_required, admin_required

destek_bp = Blueprint("destek", __name__, url_prefix="/destek")

KONULAR = [
    "Fatura & Ödeme",
    "Raporlar & Analiz",
    "Yapay Zekâ Asistanı",
    "Dışa Aktarma / PDF",
    "Hesap & Kullanıcı",
    "Teknik Sorun",
    "Öneri & Geri Bildirim",
    "Diğer",
]

SSS = [
    ("Fatura PDF nasıl indirilir?",
     "Faturalar listesinden ilgili faturaya tıklayın, ardından '🖨️ Yazdır / PDF' butonuna basın. Tarayıcınızın yazdırma ekranında 'PDF olarak kaydet' seçeneğini kullanın."),
    ("Pro planı kimler etkinleştirebilir?",
     "Pro sürümü yalnızca sistem yöneticisi (Admin) etkinleştirebilir. Admin panelinden istediğiniz kullanıcıya '✨ Pro Ver' butonuyla atayabilirsiniz."),
    ("Yapay Zekâ Asistanı nasıl çalışır?",
     "AI Asistan, işletmenizin gerçek finansal verilerini (ciro, gider, alacak, stok) okuyarak size özel tavsiyeler ve analizler üretir. Sol menüden 'AI Asistan' sekmesine gidin."),
    ("Verilerimi nasıl yedeklerim?",
     "Sol menüden 'Yedekleme' sekmesine girin ve '+ Yeni Yedek Oluştur' butonuna basın. Yedek dosyasını bilgisayarınıza indirebilirsiniz."),
    ("Şirket logomu nasıl eklerim?",
     "Ayarlar → Kişiselleştirme bölümünden logo yükleyebilirsiniz. Logo fatura çıktılarında ve sidebar'da görünür."),
    ("KDV beyan özetini nasıl görürüm?",
     "Raporlar & Analiz sayfasında 'KDV Özeti' kartı otomatik olarak hesaplanmış değerleri gösterir. Tarih filtresi ile döneme göre daraltabilirsiniz."),
]


@destek_bp.route("/", methods=["GET", "POST"])
@login_required
@pro_required
def index():
    repo = get_repo()
    uid = session.get("user_id")
    rol = session.get("user_role")

    if request.method == "POST":
        konu = request.form.get("konu", "").strip()
        mesaj = request.form.get("mesaj", "").strip()
        if not konu or not mesaj:
            flash("Konu ve mesaj alanları zorunludur.", "warning")
        elif len(mesaj) < 10:
            flash("Mesajınız çok kısa, lütfen daha ayrıntılı açıklayın.", "warning")
        else:
            repo.create_ticket(uid, konu, mesaj)
            flash("Talebiniz alındı! En kısa sürede yanıt vereceğiz. 🎯", "success")
            return redirect(url_for("destek.index"))

    talepler = repo.list_tickets() if rol == "admin" else repo.list_tickets(uid)
    return render_template("destek/index.html", konular=KONULAR, sss=SSS, talepler=talepler)


@destek_bp.route("/kapat/<int:tid>", methods=["POST"])
@admin_required
def kapat(tid):
    get_repo().close_ticket(tid)
    flash("Talep kapatıldı.", "info")
    return redirect(url_for("destek.index"))
