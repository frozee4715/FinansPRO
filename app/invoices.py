"""Fatura modülü — listele, oluştur (otomatik KDV/iskonto), detay, sil,
teklif/proforma, e-posta gönderme."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from .data.repository import get_repo
from .security import login_required

invoices_bp = Blueprint("invoices", __name__, url_prefix="/faturalar")


# ============================================================
#  Fatura fotoğrafından okuma (AI / OCR)
# ============================================================

_FATURA_OKU_ISTEMI = (
    "Bu bir fatura veya fiş fotoğrafı. Görüntüdeki bilgileri çıkar ve SADECE "
    "geçerli bir JSON nesnesi döndür; JSON dışında hiçbir metin, açıklama veya "
    "kod çiti yazma. Bulamadığın metin alanını boş string (\"\") yap. Sayısal "
    "alanlara yalnızca rakam ve nokta koy (para birimi simgesi, virgül veya "
    "binlik ayıracı KOYMA). Tarihleri YYYY-AA-GG biçimine çevir. KDV'yi yüzde "
    "oranı olarak ver (örn. 20). Satıcı/firma ünvanını musteri_adi'na yaz. "
    "Toplam birden çok kalemse en belirgin/ana kalemi kullan.\n"
    "Beklenen JSON şeması:\n"
    "{\n"
    '  "fatura_no": "",\n'
    '  "tarih": "YYYY-AA-GG",\n'
    '  "vade_tarihi": "YYYY-AA-GG",\n'
    '  "fatura_tipi": "Satış",\n'
    '  "musteri_adi": "",\n'
    '  "urun_kodu": "",\n'
    '  "aciklama": "",\n'
    '  "birim_fiyat": 0,\n'
    '  "miktar": 1,\n'
    '  "iskonto": 0,\n'
    '  "kdv": 20\n'
    "}"
)


def _match_customer(repo, musteri_adi):
    """Okunan satıcı/müşteri adını mevcut müşterilerle eşleştirir; id|None."""
    ad = (musteri_adi or "").strip().lower()
    if not ad:
        return None
    for m in repo.customer_options():
        unvan = (m["unvan"] or "").lower()
        if unvan and (ad in unvan or unvan in ad):
            return m["id"]
    return None


@invoices_bp.route("/oku", methods=["POST"])
@login_required
def oku():
    """Fatura fotoğrafını (data URL) AI ile okuyup form alanlarını döndürür."""
    data = request.get_json(silent=True) or {}
    image = (data.get("image") or "").strip()
    if not image.startswith("data:image/"):
        return jsonify({"ok": False, "hata": "Geçerli bir görüntü gönderilmedi."}), 400

    from .ai import vision_json
    veri, hata = vision_json(image, _FATURA_OKU_ISTEMI)
    if hata:
        return jsonify({"ok": False, "hata": hata}), 502

    musteri_id = _match_customer(get_repo(), veri.get("musteri_adi"))
    return jsonify({"ok": True, "veri": veri, "musteri_id": musteri_id, "kaynak": "ai"})


# Yüklenen belge için makul üst sınır (10 MB)
_MAX_BELGE_BYTES = 10 * 1024 * 1024


@invoices_bp.route("/belge-yukle", methods=["POST"])
@login_required
def belge_yukle():
    """e-Fatura/e-Arşiv belgesini (XML/PDF) KODLA okur; gerekirse AI'ya düşer.

    - .xml  → UBL-TR parse (kesin, ücretsiz)
    - .pdf  → gömülü XML varsa parse (kesin); yoksa ilk sayfa görseli → AI vision
    Yanıt fotoğraf yolu (`oku`) ile aynı şekildedir: {ok, veri, musteri_id, kaynak}.
    """
    f = request.files.get("dosya")
    if not f or not f.filename:
        return jsonify({"ok": False, "hata": "Belge seçilmedi."}), 400

    raw = f.read()
    if not raw:
        return jsonify({"ok": False, "hata": "Belge boş."}), 400
    if len(raw) > _MAX_BELGE_BYTES:
        return jsonify({"ok": False, "hata": "Belge 10 MB'tan büyük olamaz."}), 400

    ad = f.filename.lower()
    from . import efatura

    if ad.endswith(".xml"):
        try:
            veri = efatura.parse_ubl_xml(raw)
        except ValueError as e:
            return jsonify({"ok": False, "hata": str(e)}), 400
        kaynak = "xml"
    elif ad.endswith(".pdf"):
        veri, image_url, hata = efatura.read_pdf(raw)
        if hata:
            return jsonify({"ok": False, "hata": hata}), 400
        if veri is not None:
            kaynak = "pdf-xml"
        else:
            # Gömülü XML yok → görseli AI vision ile oku
            from .ai import vision_json
            veri, hata = vision_json(image_url, _FATURA_OKU_ISTEMI)
            if hata:
                return jsonify({"ok": False, "hata": hata}), 502
            kaynak = "ai"
    else:
        return jsonify({"ok": False,
                        "hata": "Yalnızca .xml veya .pdf desteklenir."}), 400

    musteri_id = _match_customer(get_repo(), veri.get("musteri_adi"))
    return jsonify({"ok": True, "veri": veri, "musteri_id": musteri_id, "kaynak": kaynak})


@invoices_bp.route("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    tip = (request.args.get("tip") or "").strip()
    faturalar = get_repo().list_invoices(q or None, tip or None)
    return render_template("invoices/list.html", faturalar=faturalar, q=q, tip=tip)


@invoices_bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    repo = get_repo()
    musteriler = repo.customer_options()

    if request.method == "POST":
        if not musteriler:
            flash("Önce en az bir müşteri eklemelisiniz.", "warning")
            return redirect(url_for("customers.create"))
        ok, result = _validate_and_calc(request.form, repo)
        if not ok:
            for h in result:
                flash(h, "danger")
            return render_template("invoices/form.html", musteriler=musteriler,
                                   form=request.form, onerilen_no=repo.next_invoice_no())
        repo.create_invoice(result)
        flash(f"Fatura {result['fatura_no']} oluşturuldu. 🧾", "success")
        return redirect(url_for("invoices.list"))

    if not musteriler:
        flash("Fatura kesmek için önce müşteri eklemeniz gerekiyor.", "warning")
    return render_template("invoices/form.html", musteriler=musteriler,
                           form=None, onerilen_no=repo.next_invoice_no())


@invoices_bp.route("/<int:iid>")
@login_required
def detail(iid):
    repo = get_repo()
    fatura = repo.get_invoice(iid)
    if not fatura:
        flash("Fatura bulunamadı.", "danger")
        return redirect(url_for("invoices.list"))
    # ödenen tutarı hesapla
    odenen = sum(p["tutar"] for p in repo.list_payments() if p["fatura_id"] == iid)
    return render_template("invoices/detail.html", f=fatura, odenen=odenen)


@invoices_bp.route("/<int:iid>/sil", methods=["POST"])
@login_required
def delete(iid):
    get_repo().delete_invoice(iid)
    flash("Fatura ve bağlı ödemeleri silindi. 🗑️", "info")
    return redirect(url_for("invoices.list"))


# ============================================================
#  GÖREV 1: Teklif / Proforma Fatura
# ============================================================

@invoices_bp.route("/teklif-olustur", methods=["GET", "POST"])
@login_required
def teklif_create():
    repo = get_repo()
    musteriler = repo.customer_options()

    if request.method == "POST":
        if not musteriler:
            flash("Önce en az bir müşteri eklemelisiniz.", "warning")
            return redirect(url_for("customers.create"))
        ok, result = _validate_and_calc(request.form, repo, fatura_tipi_default="Teklif")
        if not ok:
            for h in result:
                flash(h, "danger")
            return render_template(
                "invoices/teklif_form.html",
                musteriler=musteriler,
                form=request.form,
                onerilen_no=repo.next_invoice_no(),
            )
        # Teklif'e özgü ek alan
        result["gecerlilik_tarihi"] = (request.form.get("gecerlilik_tarihi") or "").strip()
        result["fatura_tipi"] = "Teklif"
        repo.create_invoice(result)
        flash(f"Teklif {result['fatura_no']} oluşturuldu.", "success")
        return redirect(url_for("invoices.list", tip="teklif"))

    if not musteriler:
        flash("Teklif oluşturmak için önce müşteri eklemeniz gerekiyor.", "warning")
    return render_template(
        "invoices/teklif_form.html",
        musteriler=musteriler,
        form=None,
        onerilen_no=repo.next_invoice_no(),
    )


@invoices_bp.route("/teklif/<int:iid>/faturalandir", methods=["POST"])
@login_required
def teklif_to_invoice(iid):
    repo = get_repo()
    teklif = repo.get_invoice(iid)
    if not teklif or teklif.get("fatura_tipi") != "Teklif":
        flash("Teklif bulunamadı.", "danger")
        return redirect(url_for("invoices.list", tip="teklif"))

    yeni_no = repo.next_invoice_no()
    repo.convert_teklif_to_invoice(iid, yeni_no)
    flash(f"Teklif faturaya dönüştürüldü. Yeni fatura no: {yeni_no}", "success")
    return redirect(url_for("invoices.list"))


# ============================================================
#  GÖREV 3: E-posta gönderme rotası
# ============================================================

@invoices_bp.route("/<int:iid>/eposta-gonder", methods=["POST"])
@login_required
def send_email(iid):
    repo = get_repo()
    fatura = repo.get_invoice(iid)
    if not fatura:
        flash("Fatura bulunamadı.", "danger")
        return redirect(url_for("invoices.list"))

    to_email = fatura.get("musteri_eposta") or ""
    to_name = fatura.get("musteri_unvan") or ""
    fatura_no = fatura.get("fatura_no") or ""

    if not to_email:
        flash("Bu müşteriye ait e-posta adresi bulunamadı.", "warning")
        return redirect(url_for("invoices.detail", iid=iid))

    from .email_utils import send_invoice_email
    ok, hata = send_invoice_email(to_email, to_name, fatura_no)
    if ok:
        flash(f"Fatura {fatura_no} e-posta ile {to_email} adresine gönderildi.", "success")
    else:
        flash(f"E-posta gönderilemedi: {hata}", "danger")

    return redirect(url_for("invoices.detail", iid=iid))


# ============================================================
#  Yardımcı: form doğrulama & hesaplama
# ============================================================

def _validate_and_calc(form, repo, fatura_tipi_default="Satış"):
    hatalar = []
    try:
        musteri_id = int(form.get("musteri_id"))
        if not repo.get_customer(musteri_id):
            hatalar.append("Geçersiz müşteri seçimi.")
    except (TypeError, ValueError):
        musteri_id = None
        hatalar.append("Müşteri seçiniz.")

    fatura_no = (form.get("fatura_no") or "").strip() or repo.next_invoice_no()
    tarih = (form.get("tarih") or "").strip()
    vade_tarihi = (form.get("vade_tarihi") or "").strip()
    fatura_tipi = (form.get("fatura_tipi") or fatura_tipi_default).strip()
    urun_kodu = (form.get("urun_kodu") or "").strip()
    aciklama = (form.get("aciklama") or "").strip()

    if not tarih:
        hatalar.append("Fatura tarihi giriniz.")

    def num(key, label, zorunlu=True):
        try:
            v = float(form.get(key) or 0)
            if v < 0:
                hatalar.append(f"{label} negatif olamaz.")
            return v
        except ValueError:
            hatalar.append(f"{label} geçerli bir sayı olmalı.")
            return 0

    birim_fiyat = num("birim_fiyat", "Birim fiyat")
    miktar = num("miktar", "Miktar")
    iskonto = num("iskonto", "İskonto %")
    kdv = num("kdv", "KDV %")

    if miktar <= 0:
        hatalar.append("Miktar 0'dan büyük olmalı.")

    if hatalar:
        return False, hatalar

    # Hesaplamalar
    ara_toplam = round(birim_fiyat * miktar, 2)
    iskonto_tutari = round(ara_toplam * iskonto / 100, 2)
    matrah = ara_toplam - iskonto_tutari
    kdv_tutari = round(matrah * kdv / 100, 2)
    toplam = round(matrah + kdv_tutari, 2)

    return True, {
        "musteri_id": musteri_id,
        "fatura_no": fatura_no,
        "tarih": tarih,
        "urun_kodu": urun_kodu,
        "acıklama": aciklama,
        "Birim_Fiyat": birim_fiyat,
        "iskonto": iskonto,
        "kdv": kdv,
        "ara_toplam": ara_toplam,
        "iskonto_tutarı": iskonto_tutari,
        "kdv_tutarı": kdv_tutari,
        "toplam_tutar": toplam,
        "fatura_tipi": fatura_tipi,
        "vade_tarihi": vade_tarihi,
        "gecerlilik_tarihi": "",
    }
