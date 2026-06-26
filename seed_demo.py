"""
Demo veritabanı tohumlama (pazarlama / sunum amaçlı).

Çalıştırma (proje kökünden):
    python seed_demo.py

Yaptığı işler:
  1) Tüm kullanıcıları ve işlem verilerini TEMİZLER.
  2) Pro yetkili bir "demo" hesabı oluşturur (giriş: demo@finanspro.com / Demo1234).
  3) Gerçekçi müşteriler, ürünler, tedarikçiler, kasa/banka hesapları,
     faturalar, ödemeler, giderler ve çek/senet kayıtları ekler.

NOT: Admin hesabı burada OLUŞTURULMAZ. Admin yalnızca ortam değişkenleri
(ADMIN_EMAIL / ADMIN_PASSWORD) ayarlandığında uygulama açılışında oluşur.

Veritabanı yolu, uygulamayla AYNI olması için config.Config.SQLITE_PATH'ten okunur.
"""
import sqlite3
from datetime import datetime, date, timedelta

from werkzeug.security import generate_password_hash

from config import Config
from app.data.repository import init_schema, SqliteRepository

DB_PATH = Config.SQLITE_PATH

# Demo hesabı bilgileri (pazarlamada paylaşılabilir)
DEMO_EMAIL = "demo@finanspro.com"
DEMO_PASS = "Demo1234"

BUGUN = date(2026, 6, 26)


def wipe(conn):
    """Tüm demo/işlem tablolarını temizler ve ID sayaçlarını sıfırlar."""
    tablolar = [
        "users", "customers", "products", "invoices", "payments", "expenses",
        "tedarikcilar", "hesaplar", "hesap_hareketleri", "cek_senet",
        "stok_hareketleri", "butce", "tekrarlayan_faturalar", "audit_log",
        "destek_talepleri", "bildirim_log", "fcm_tokens", "settings",
    ]
    conn.execute("PRAGMA foreign_keys = OFF")
    for t in tablolar:
        try:
            conn.execute(f"DELETE FROM {t}")
        except sqlite3.OperationalError:
            pass
    try:
        conn.execute("DELETE FROM sqlite_sequence")
    except sqlite3.OperationalError:
        pass
    conn.commit()


def compute_invoice(base, iskonto, kdv):
    """ara_toplam, iskonto/kdv tutarı ve toplamı hesaplar."""
    ara = round(base, 2)
    isk = round(ara * iskonto / 100, 2)
    matrah = ara - isk
    kdv_t = round(matrah * kdv / 100, 2)
    toplam = round(matrah + kdv_t, 2)
    return ara, isk, kdv_t, toplam


def _ensure_demo_user(repo):
    """Demo kullanıcısını (Pro) garanti eder; id döndürür."""
    mevcut = repo.get_user_by_login(DEMO_EMAIL)
    if mevcut:
        uid = mevcut["id"]
    else:
        uid = repo.create_user(
            name="Demo Kullanıcı",
            age=30,
            eposta=DEMO_EMAIL,
            parola_hash=generate_password_hash(DEMO_PASS),
            rol="kullanici",
        )
    repo.set_user_plan(uid, "pro")
    return uid


def populate(repo, conn):
    """İş verisini (ayarlar, müşteri, ürün, fatura, ...) ekler. Silme YAPMAZ."""
    # --- Şirket / marka ayarları ------------------------------------------
    repo.set_setting("sirket_adi", "FinansPro Demo Ticaret A.Ş.")
    repo.set_setting("vergi_no", "1234567890")
    repo.set_setting("adres", "Atatürk Cad. No:42, Çankaya / Ankara")
    repo.set_setting("telefon", "0312 444 12 34")
    repo.set_setting("eposta", "info@finanspro.com")
    repo.set_setting("para_birimi", "₺")
    repo.set_setting("plan", "pro")

    # --- Müşteriler -------------------------------------------------------
    musteriler = [
        ("ABC Teknoloji A.Ş.", "4830127456", "Maslak Mah. No:1, Sarıyer/İstanbul", "0212 555 10 20", "muhasebe@abcteknoloji.com"),
        ("Yılmaz İnşaat Ltd. Şti.", "9920038471", "Kızılay Mah. No:15, Çankaya/Ankara", "0312 222 33 44", "info@yilmazinsaat.com"),
        ("Demir Gıda San. Tic.", "3450912678", "Organize San. Böl. 5. Cad., Konya", "0332 345 67 89", "satinalma@demirgida.com"),
        ("Kaya Tekstil", "7710456390", "Merinos Mah. No:88, Osmangazi/Bursa", "0224 111 22 33", "info@kayatekstil.com"),
        ("Öztürk Otomotiv", "6120783459", "Sanayi Sitesi C Blok No:7, İzmir", "0232 888 99 00", "muhasebe@ozturkoto.com"),
    ]
    for unvan, vno, adres, tel, eposta in musteriler:
        repo.create_customer(unvan=unvan, vergi_no=vno, adres=adres, telefon=tel, eposta=eposta)
    print(f"• {len(musteriler)} müşteri eklendi.")

    # --- Ürünler ----------------------------------------------------------
    urunler = [
        ("Dizüstü Bilgisayar 15.6\"", "Intel i7, 16GB RAM, 512GB SSD", 28500.0, 24, "Bilgisayar"),
        ("Ofis Koltuğu (Ergonomik)", "Bel destekli, ayarlanabilir", 4250.0, 60, "Mobilya"),
        ("Lazer Yazıcı", "Çift taraflı, ağ bağlantılı", 7800.0, 15, "Donanım"),
        ("27\" Monitör", "QHD IPS, 75Hz", 6900.0, 30, "Donanım"),
        ("Kablosuz Klavye-Mouse Set", "Türkçe Q, sessiz tuş", 950.0, 4, "Aksesuar"),
        ("Web Tasarım Hizmeti", "Kurumsal site paketi (yıllık)", 18000.0, 999, "Hizmet"),
    ]
    for ad, acik, fiyat, stok, kat in urunler:
        repo.create_product(name=ad, aciklama=acik, birim_fiyat=fiyat, stok=stok, kategori=kat)
    print(f"• {len(urunler)} ürün eklendi.")

    # --- Tedarikçiler -----------------------------------------------------
    tedarikciler = [
        ("Mega Toptan Bilişim", "5510239847", "Bağcılar/İstanbul", "0212 600 11 22", "satis@megatoptan.com", "Ana donanım tedarikçisi"),
        ("Anadolu Lojistik", "8830471265", "Esenyurt/İstanbul", "0212 700 33 44", "operasyon@anadolulojistik.com", "Kargo & nakliye"),
        ("Bursa Ofis Kırtasiye", "2240918736", "Nilüfer/Bursa", "0224 500 55 66", "info@bursaofis.com", "Sarf malzeme"),
    ]
    for unvan, vno, adres, tel, eposta, notlar in tedarikciler:
        repo.create_supplier(unvan=unvan, vergi_no=vno, adres=adres, telefon=tel, eposta=eposta, notlar=notlar)
    print(f"• {len(tedarikciler)} tedarikçi eklendi.")

    # --- Kasa / Banka hesapları -------------------------------------------
    repo.create_account(ad="Nakit Kasa", tur="Kasa", para_birimi="₺", bakiye_baslangic=15000.0, aciklama="Ofis kasası")
    repo.create_account(ad="Ziraat Bankası TL", tur="Banka", para_birimi="₺", bakiye_baslangic=185000.0, aciklama="Ana vadesiz hesap")
    repo.create_account(ad="Garanti POS", tur="Banka", para_birimi="₺", bakiye_baslangic=42000.0, aciklama="Kart tahsilatları")
    # Birkaç hesap hareketi
    repo.add_movement(hesap_id=2, tarih=(BUGUN - timedelta(days=20)).isoformat(), aciklama="Müşteri tahsilatı", tutar=35000.0, tip="Giriş", referans="FAT2026000001")
    repo.add_movement(hesap_id=2, tarih=(BUGUN - timedelta(days=12)).isoformat(), aciklama="Tedarikçi ödemesi", tutar=-22000.0, tip="Çıkış", referans="Mega Toptan")
    repo.add_movement(hesap_id=1, tarih=(BUGUN - timedelta(days=5)).isoformat(), aciklama="Kasa devir", tutar=5000.0, tip="Giriş", referans="")
    print("• 3 kasa/banka hesabı + hareketler eklendi.")

    # --- Faturalar --------------------------------------------------------
    # (müşteri_id, gün_önce, ürün_kodu, açıklama, base, iskonto%, kdv%, tip)
    fatura_tanim = [
        (1, 165, "Dizüstü Bilgisayar 15.6\"", "5 adet dizüstü bilgisayar", 142500.0, 5, 20, "Satış"),
        (2, 140, "27\" Monitör",               "10 adet monitör",           69000.0, 0, 20, "Satış"),
        (3, 120, "Web Tasarım Hizmeti",        "Kurumsal site + bakım",     18000.0, 0, 20, "Satış"),
        (4, 95,  "Ofis Koltuğu (Ergonomik)",  "12 adet ofis koltuğu",      51000.0, 10, 20, "Satış"),
        (5, 70,  "Lazer Yazıcı",               "4 adet yazıcı",             31200.0, 0, 20, "Satış"),
        (1, 45,  "Kablosuz Klavye-Mouse Set",  "30 set klavye-mouse",        28500.0, 0, 20, "Satış"),
        (2, 20,  "Dizüstü Bilgisayar 15.6\"",  "3 adet dizüstü bilgisayar", 85500.0, 0, 20, "Satış"),
        (3, 8,   "27\" Monitör",               "5 adet monitör",            34500.0, 0, 20, "Satış"),
        # Alış faturaları (tedarikten)
        (1, 100, "TEDARIK", "Toptan donanım alımı (Mega Toptan)", 96000.0, 0, 20, "Alış"),
        (2, 35,  "TEDARIK", "Ofis mobilya alımı",                 24000.0, 0, 20, "Alış"),
    ]
    fatura_ids = []
    for i, (mid, gun, kod, acik, base, isk, kdv, tip) in enumerate(fatura_tanim, start=1):
        tarih = (BUGUN - timedelta(days=gun))
        ara, isk_t, kdv_t, toplam = compute_invoice(base, isk, kdv)
        no = f"FAT2026{i:06d}"
        repo.create_invoice({
            "musteri_id": mid,
            "fatura_no": no,
            "tarih": tarih.isoformat(),
            "urun_kodu": kod,
            "acıklama": acik,
            "Birim_Fiyat": base,
            "iskonto": isk,
            "kdv": kdv,
            "ara_toplam": ara,
            "iskonto_tutarı": isk_t,
            "kdv_tutarı": kdv_t,
            "toplam_tutar": toplam,
            "fatura_tipi": tip,
            "vade_tarihi": (tarih + timedelta(days=30)).isoformat(),
            "gecerlilik_tarihi": "",
        })
        fatura_ids.append((i, toplam, tip))
    print(f"• {len(fatura_tanim)} fatura eklendi (satış + alış).")

    # --- Ödemeler (bazı satış faturaları tamamen/kısmen tahsil) -----------
    odeme_plani = [
        (1, 165 - 25, "full", "Havale"),
        (2, 140 - 18, "full", "Havale"),
        (3, 120 - 10, "full", "Kredi Kartı"),
        (4, 95 - 15,  "full", "Havale"),
        (5, 70 - 30,  "half", "Nakit"),
    ]
    odeme_say = 0
    for fid, gun, oran, tip in odeme_plani:
        _no, toplam, _t = fatura_ids[fid - 1]
        tutar = toplam if oran == "full" else round(toplam / 2, 2)
        repo.create_payment(
            fatura_id=fid,
            odeme_tarihi=(BUGUN - timedelta(days=gun)).isoformat(),
            tutar=tutar,
            odeme_tipi=tip,
        )
        odeme_say += 1
    print(f"• {odeme_say} ödeme eklendi.")

    # --- Giderler ---------------------------------------------------------
    giderler = [
        (170, "Kira", "Ofis kira ödemesi", 22000.0, "Havale"),
        (160, "Personel", "Maaş ödemeleri", 95000.0, "Havale"),
        (155, "Fatura", "Elektrik faturası", 3400.0, "Otomatik Ödeme"),
        (150, "Fatura", "İnternet & telefon", 1850.0, "Kredi Kartı"),
        (90,  "Yakıt", "Servis aracı yakıt", 4200.0, "Kredi Kartı"),
        (40,  "Pazarlama", "Sosyal medya reklamları", 7500.0, "Kredi Kartı"),
        (15,  "Kira", "Ofis kira ödemesi", 22000.0, "Havale"),
    ]
    for gun, kat, acik, tutar, tip in giderler:
        repo.create_expense(
            tarih=(BUGUN - timedelta(days=gun)).isoformat(),
            kategori=kat, aciklama=acik, tutar=tutar, odeme_tipi=tip,
        )
    print(f"• {len(giderler)} gider eklendi.")

    # --- Çek / Senet ------------------------------------------------------
    cekler = [
        ("Çek", "ABC Teknoloji A.Ş.", 35000.0, (BUGUN + timedelta(days=15)).isoformat(), "Beklemede", "Müşteri çeki"),
        ("Senet", "Yılmaz İnşaat Ltd. Şti.", 18000.0, (BUGUN + timedelta(days=45)).isoformat(), "Beklemede", "Vadeli satış"),
        ("Çek", "Mega Toptan Bilişim", 22000.0, (BUGUN + timedelta(days=5)).isoformat(), "Beklemede", "Tedarikçi ödemesi"),
    ]
    for tur, taraf, tutar, vade, durum, notlar in cekler:
        repo.create_check(tur=tur, taraf=taraf, tutar=tutar, vade_tarihi=vade, durum=durum, notlar=notlar)
    print(f"• {len(cekler)} çek/senet eklendi.")


def _has_business_data(conn):
    """DB'de zaten iş verisi (müşteri) var mı?"""
    try:
        return conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] > 0
    except sqlite3.OperationalError:
        return False


def seed():
    """ELLE tam sıfırlama: tüm veriyi siler, demo hesabı + zengin demo veri kurar."""
    init_schema(DB_PATH)
    repo = SqliteRepository(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print(f"DB: {DB_PATH}")
    wipe(conn)
    print("• Eski veriler temizlendi.")
    _ensure_demo_user(repo)
    print(f"• Demo hesabı: {DEMO_EMAIL} / {DEMO_PASS} (Pro)")
    populate(repo, conn)
    conn.close()
    print("\n[OK] Demo veritabanı hazır.")
    print(f"   Giriş: {DEMO_EMAIL}  |  Şifre: {DEMO_PASS}")
    print("   Admin: yalnızca ADMIN_EMAIL/ADMIN_PASSWORD ayarlıysa açılışta oluşur.")


def seed_if_empty():
    """AÇILIŞTA güvenli tohumlama: yalnızca DB'de iş verisi yoksa demo veriyi
    kurar. Mevcut veriyi ASLA silmez. Demo hesabını her durumda garanti eder.
    Tohumlama yapıldıysa True döner."""
    init_schema(DB_PATH)
    repo = SqliteRepository(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_demo_user(repo)
        if _has_business_data(conn):
            return False
        populate(repo, conn)
        return True
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
