"""
e-Fatura / e-Arşiv belgelerini KODLA okuma motoru.

Türkiye'de e-Fatura/e-Arşiv belgeleri UBL-TR (XML) biçimindedir; bunlar zaten
dijital ve yapılandırılmış olduğundan AI'ya gerek yoktur: doğrudan kodla parse
edilir → kesin, ücretsiz, hızlı.

Çıktı, AI vision yolu (app/invoices.py `_FATURA_OKU_ISTEMI`) ile AYNI JSON
şemasıdır; böylece formdaki doldurma JS'i ve müşteri eşleştirme aynen yeniden
kullanılır:
    fatura_no, tarih, vade_tarihi, fatura_tipi, musteri_adi,
    urun_kodu, aciklama, birim_fiyat, miktar, iskonto, kdv

Çok kalemli faturalar tek satıra (resmî toplamlar) eşlenir; böylece form
toplamı resmî fatura toplamıyla birebir tutar.
"""
import base64

# Güvenli XML parse (XXE / billion-laughs koruması — belge güvenilmez kaynaktan)
from defusedxml import ElementTree as ET


# ============================================================
#  Namespace-toleranslı XML yardımcıları
# ============================================================
#  UBL-TR'de prefix değişebilir ve belge bir XAdES imza zarfı içinde olabilir.
#  Bu yüzden tam ad ({ns}tag) yerine YEREL ADA (local-name) göre arıyoruz.

def _local(tag):
    """'{namespace}Invoice' → 'Invoice' (namespace'i at)."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find(el, *path):
    """Yerel ada göre iç içe ilk eşleşen elemanı döndürür (yoksa None).

    Örn. _find(root, "AccountingSupplierParty", "Party", "PartyName", "Name")
    """
    cur = el
    for ad in path:
        if cur is None:
            return None
        bulunan = None
        for child in cur.iter():
            if child is not cur and _local(child.tag) == ad:
                bulunan = child
                break
        cur = bulunan
    return cur


def _findall(el, ad):
    """Ağacın tamamında yerel adı eşleşen tüm elemanlar."""
    return [c for c in el.iter() if _local(c.tag) == ad]


def _text(el, *path):
    """_find sonucunun metni (kırpılmış); yoksa ''."""
    node = _find(el, *path)
    return (node.text or "").strip() if node is not None else ""


def _num(s):
    """Para/sayı metnini float'a çevirir; bozuksa 0.0."""
    try:
        return float((s or "0").strip())
    except (ValueError, TypeError):
        return 0.0


def _invoice_root(tree_root):
    """İmza zarfı vb. içinde olsa bile Invoice elemanını bulur."""
    if _local(tree_root.tag) == "Invoice":
        return tree_root
    for el in tree_root.iter():
        if _local(el.tag) == "Invoice":
            return el
    return tree_root


# ============================================================
#  UBL-TR XML → ortak JSON şeması
# ============================================================

def parse_ubl_xml(xml_bytes):
    """UBL-TR e-Fatura XML byte'larını ortak fatura sözlüğüne çevirir.

    Hata durumunda ValueError yükseltir.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:  # defusedxml çeşitli istisnalar atabilir
        raise ValueError(f"XML çözümlenemedi: {e}")

    inv = _invoice_root(root)

    # --- Karşı taraf (gelen fatura → satıcı) ---
    supplier = _find(inv, "AccountingSupplierParty", "Party")
    musteri_adi = ""
    if supplier is not None:
        musteri_adi = (
            _text(supplier, "PartyName", "Name")
            or _text(supplier, "PartyLegalEntity", "RegistrationName")
        )

    # --- Resmî toplamlar (aggregate / tek satır eşlemesi) ---
    lmt = _find(inv, "LegalMonetaryTotal")
    matrah = _num(_text(lmt, "TaxExclusiveAmount")) if lmt is not None else 0.0

    # Toplam KDV: en üst düzey TaxTotal/TaxAmount (varsa)
    kdv_tutari = 0.0
    tax_total = _find(inv, "TaxTotal")
    if tax_total is not None:
        kdv_tutari = _num(_text(tax_total, "TaxAmount"))

    # Efektif KDV oranı (matrah üzerinden)
    if matrah > 0:
        kdv_oran = round(kdv_tutari / matrah * 100)
    else:
        kdv_oran = 0

    # --- Kalemler ---
    lines = _findall(inv, "InvoiceLine")
    if len(lines) == 1:
        item = _find(lines[0], "Item")
        aciklama = _text(item, "Name") if item is not None else ""
        urun_kodu = _text(item, "SellersItemIdentification", "ID") if item is not None else ""
    elif len(lines) > 1:
        ilk_item = _find(lines[0], "Item")
        ilk_ad = _text(ilk_item, "Name") if ilk_item is not None else ""
        aciklama = f"{len(lines)} kalem" + (f": {ilk_ad} vb." if ilk_ad else "")
        urun_kodu = ""
    else:
        aciklama = ""
        urun_kodu = ""

    return {
        "fatura_no": _text(inv, "ID"),
        "tarih": _text(inv, "IssueDate"),
        "vade_tarihi": _text(inv, "PaymentMeans", "PaymentDueDate"),
        "fatura_tipi": "Alış",  # yön XML'den kesin türetilemez; kullanıcı onaylar
        "musteri_adi": musteri_adi,
        "urun_kodu": urun_kodu,
        "aciklama": aciklama,
        "birim_fiyat": round(matrah, 2),
        "miktar": 1,
        "iskonto": 0,
        "kdv": kdv_oran,
    }


# ============================================================
#  PDF → (kesin XML parse) veya (AI için görsel)
# ============================================================

def _looks_like_ubl(data):
    """Byte içeriği bir UBL/Invoice XML'i gibi mi görünüyor?"""
    bas = data[:2000].lower()
    return b"<invoice" in bas or b"ubl" in bas or b"<?xml" in bas


def read_pdf(pdf_bytes):
    """e-Arşiv/e-Fatura PDF'ini okur.

    (veri, image_data_url, hata) döndürür:
      - Gömülü UBL XML bulunursa: (veri_dict, None, None) — KESİN, AI yok.
      - Bulunmazsa: (None, "data:image/png;base64,...", None) — ilk sayfa
        görseli; çağıran taraf AI vision'a verir.
      - Açılamazsa: (None, None, hata_metni).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None, None, ("PDF desteği için sunucuda 'pymupdf' kurulu "
                            "olmalı.")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return None, None, f"PDF açılamadı: {e}"

    try:
        # 1) Gömülü XML var mı? (e-Arşiv PDF'leri sıklıkla UBL XML gömer)
        try:
            adlar = doc.embfile_names()
        except Exception:
            adlar = []
        for ad in adlar:
            try:
                icerik = doc.embfile_get(ad)
            except Exception:
                continue
            if ad.lower().endswith(".xml") or _looks_like_ubl(icerik):
                try:
                    return parse_ubl_xml(icerik), None, None
                except ValueError:
                    continue  # bu gömülü dosya UBL değilmiş, diğerlerine bak

        # 2) Gömülü XML yok → ilk sayfayı görsele çevir (AI dalı)
        if doc.page_count == 0:
            return None, None, "PDF boş görünüyor."
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=150)
        png = pix.tobytes("png")
        data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        return None, data_url, None
    finally:
        doc.close()
