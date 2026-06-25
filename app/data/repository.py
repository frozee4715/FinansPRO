"""
Repository deseni — SQLite uygulaması.

Tek bir arayüz (SqliteRepository) tüm CRUD işlemlerini sağlar. Firebase'e
geçişte aynı metod imzalarına sahip FirebaseRepository yazılır ve
get_repo() onu döndürür.
"""
import sqlite3
from datetime import datetime, timedelta
from flask import current_app, g


# ---------------------------------------------------------------------------
# Bağlantı yönetimi
# ---------------------------------------------------------------------------
def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row          # sözlük benzeri satır erişimi
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Şema kurulumu / göçü
# ---------------------------------------------------------------------------
def init_schema(path):
    """Tabloları ve web için gereken yeni sütunları oluşturur (idempotent)."""
    conn = _connect(path)
    cur = conn.cursor()

    # Mevcut CLI tablolarıyla uyumlu temel tablolar
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, age INTEGER, eposta TEXT, sifre TEXT, yetki TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unvan TEXT, vergi_no TEXT, adres TEXT, telefon TEXT, eposta TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, aciklama TEXT, birim_fiyat REAL, stok INTEGER)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS invoices(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        musteri_id INTEGER, fatura_no TEXT, tarih TEXT, urun_kodu TEXT,
        acıklama TEXT, Birim_Fiyat REAL, iskonto REAL, kdv REAL,
        ara_toplam REAL, iskonto_tutarı REAL, kdv_tutarı REAL,
        toplam_tutar REAL, fatura_tipi TEXT, vade_tarihi TEXT,
        FOREIGN KEY(musteri_id) REFERENCES customers(id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fatura_id INTEGER, odeme_tarihi TEXT, tutar REAL, odeme_tipi TEXT,
        FOREIGN KEY(fatura_id) REFERENCES invoices(id))""")

    # Giderler / masraflar
    cur.execute("""CREATE TABLE IF NOT EXISTS expenses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tarih TEXT, kategori TEXT, aciklama TEXT, tutar REAL, odeme_tipi TEXT,
        olusturulma TEXT)""")

    # Uygulama ayarları (anahtar/değer) — şirket bilgisi, plan, vb.
    cur.execute("""CREATE TABLE IF NOT EXISTS settings(
        anahtar TEXT PRIMARY KEY, deger TEXT)""")

    # Destek talepleri
    cur.execute("""CREATE TABLE IF NOT EXISTS destek_talepleri(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, konu TEXT, mesaj TEXT,
        durum TEXT DEFAULT 'acik',
        olusturma TEXT DEFAULT CURRENT_TIMESTAMP)""")

    # Tedarikçiler
    cur.execute("""CREATE TABLE IF NOT EXISTS tedarikcilar(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unvan TEXT, vergi_no TEXT, adres TEXT, telefon TEXT,
        eposta TEXT, notlar TEXT, olusturulma TEXT)""")

    # Kasa / Banka hesapları
    cur.execute("""CREATE TABLE IF NOT EXISTS hesaplar(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad TEXT, tur TEXT, para_birimi TEXT DEFAULT '₺',
        bakiye_baslangic REAL DEFAULT 0, aciklama TEXT, aktif INTEGER DEFAULT 1)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS hesap_hareketleri(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hesap_id INTEGER, tarih TEXT, aciklama TEXT,
        tutar REAL, tip TEXT, referans TEXT,
        olusturulma TEXT,
        FOREIGN KEY(hesap_id) REFERENCES hesaplar(id))""")

    # Çek / Senet
    cur.execute("""CREATE TABLE IF NOT EXISTS cek_senet(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tur TEXT, taraf TEXT, tutar REAL,
        vade_tarihi TEXT, durum TEXT DEFAULT 'Beklemede',
        notlar TEXT, olusturulma TEXT)""")

    # Stok hareketleri
    cur.execute("""CREATE TABLE IF NOT EXISTS stok_hareketleri(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        urun_id INTEGER, tur TEXT, miktar INTEGER,
        aciklama TEXT, referans TEXT, olusturulma TEXT,
        FOREIGN KEY(urun_id) REFERENCES products(id))""")

    # Bütçe
    cur.execute("""CREATE TABLE IF NOT EXISTS butce(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        yil INTEGER, ay INTEGER, kategori TEXT,
        hedef_tutar REAL,
        UNIQUE(yil, ay, kategori))""")

    # Denetim kaydı
    cur.execute("""CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_id INTEGER, kullanici_adi TEXT,
        islem TEXT, tablo TEXT, kayit_id INTEGER,
        detay TEXT, tarih TEXT)""")

    # Tekrarlayan faturalar
    cur.execute("""CREATE TABLE IF NOT EXISTS tekrarlayan_faturalar(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        musteri_id INTEGER, aciklama TEXT, tutar REAL,
        kdv REAL DEFAULT 20, periyot TEXT,
        sonraki_tarih TEXT, aktif INTEGER DEFAULT 1,
        olusturulma TEXT)""")

    # Gönderilen bildirim kaydı (tekrar gönderimi önler)
    cur.execute("""CREATE TABLE IF NOT EXISTS bildirim_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        tip TEXT NOT NULL,
        referans TEXT NOT NULL,
        tarih TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, tip, referans))""")

    # FCM Push bildirim token'ları
    cur.execute("""CREATE TABLE IF NOT EXISTS fcm_tokens(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT NOT NULL UNIQUE,
        olusturulma TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)""")

    # Web için users tablosuna eklenen sütunlar (varsa atlar)
    _add_column(cur, "users", "parola_hash", "TEXT")
    _add_column(cur, "users", "rol", "TEXT DEFAULT 'kullanici'")
    _add_column(cur, "users", "aktif", "INTEGER DEFAULT 1")
    _add_column(cur, "users", "basarisiz_giris", "INTEGER DEFAULT 0")
    _add_column(cur, "users", "kilit_bitis", "TEXT")
    _add_column(cur, "users", "olusturulma", "TEXT")
    _add_column(cur, "users", "son_giris", "TEXT")
    _add_column(cur, "users", "plan", "TEXT DEFAULT 'free'")

    # Mevcut tablolara yeni sütunlar
    _add_column(cur, "products", "kategori", "TEXT DEFAULT ''")
    _add_column(cur, "invoices", "tur", "TEXT DEFAULT 'Fatura'")
    _add_column(cur, "invoices", "gecerlilik_tarihi", "TEXT")

    conn.commit()
    conn.close()


def _add_column(cur, table, column, decl):
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    except sqlite3.OperationalError:
        pass  # sütun zaten var


# ---------------------------------------------------------------------------
# SQLite Repository
# ---------------------------------------------------------------------------
class SqliteRepository:
    def __init__(self, path):
        self.path = path

    def _conn(self):
        return _connect(self.path)

    # ----- Kullanıcılar -------------------------------------------------
    def get_user_by_login(self, identifier):
        """E-posta VEYA isim ile kullanıcı bulur."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM users WHERE eposta = ? OR name = ? LIMIT 1",
            (identifier, identifier),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user(self, user_id):
        conn = self._conn()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def email_exists(self, eposta):
        conn = self._conn()
        row = conn.execute("SELECT 1 FROM users WHERE eposta = ?", (eposta,)).fetchone()
        conn.close()
        return row is not None

    def create_user(self, *, name, age, eposta, parola_hash, rol="kullanici"):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO users(name, age, eposta, parola_hash, rol, yetki,
                                 aktif, basarisiz_giris, olusturulma)
               VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?)""",
            (name, age, eposta, parola_hash, rol, rol,
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return new_id

    def list_users(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, name, age, eposta, rol, aktif, son_giris, olusturulma, "
            "COALESCE(plan,'free') AS plan FROM users ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def count_users(self):
        return self._scalar("SELECT COUNT(*) FROM users")

    def update_user_role(self, user_id, rol):
        self._exec("UPDATE users SET rol = ?, yetki = ? WHERE id = ?", (rol, rol, user_id))

    def set_user_active(self, user_id, aktif):
        self._exec("UPDATE users SET aktif = ? WHERE id = ?", (1 if aktif else 0, user_id))

    def set_user_plan(self, user_id, plan):
        """Kullanıcı planını ayarlar: 'free' veya 'pro'."""
        self._exec("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))

    def get_user_plan(self, user_id):
        conn = self._conn()
        row = conn.execute("SELECT plan FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return (row["plan"] or "free") if row else "free"

    def delete_user(self, user_id):
        self._exec("DELETE FROM users WHERE id = ?", (user_id,))

    # ----- Giriş güvenliği (kilitleme) ---------------------------------
    def register_failed_login(self, user_id, max_attempts, lockout_minutes):
        """Başarısız giriş sayar; eşiği aşınca hesabı kilitler.
        Kalan deneme hakkını döndürür (kilitlenmişse 0)."""
        conn = self._conn()
        cur = conn.cursor()
        row = cur.execute(
            "SELECT basarisiz_giris FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        sayac = (row["basarisiz_giris"] or 0) + 1
        if sayac >= max_attempts:
            kilit = (datetime.now() + timedelta(minutes=lockout_minutes)).isoformat(timespec="seconds")
            cur.execute(
                "UPDATE users SET basarisiz_giris = ?, kilit_bitis = ? WHERE id = ?",
                (sayac, kilit, user_id),
            )
            kalan = 0
        else:
            cur.execute(
                "UPDATE users SET basarisiz_giris = ? WHERE id = ?", (sayac, user_id)
            )
            kalan = max_attempts - sayac
        conn.commit()
        conn.close()
        return kalan

    def is_locked(self, user):
        """Kullanıcı şu an kilitli mi? (kalan saniye, kilitliyse > 0)."""
        kb = user.get("kilit_bitis")
        if not kb:
            return 0
        try:
            bitis = datetime.fromisoformat(kb)
        except ValueError:
            return 0
        if bitis > datetime.now():
            return int((bitis - datetime.now()).total_seconds())
        return 0

    def reset_login_state(self, user_id):
        self._exec(
            "UPDATE users SET basarisiz_giris = 0, kilit_bitis = NULL, son_giris = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), user_id),
        )

    # ----- Dashboard sayaçları -----------------------------------------
    def dashboard_stats(self):
        conn = self._conn()
        c = conn.cursor()

        def safe(sql):
            try:
                return c.execute(sql).fetchone()[0] or 0
            except sqlite3.OperationalError:
                return 0

        stats = {
            "musteri": safe("SELECT COUNT(*) FROM customers"),
            "urun": safe("SELECT COUNT(*) FROM products"),
            "fatura": safe("SELECT COUNT(*) FROM invoices"),
            "ciro": safe("SELECT COALESCE(SUM(toplam_tutar),0) FROM invoices WHERE fatura_tipi='Satış'"),
            "tahsilat": safe("SELECT COALESCE(SUM(tutar),0) FROM payments"),
            "dusuk_stok": safe("SELECT COUNT(*) FROM products WHERE stok <= 5"),
        }
        conn.close()
        return stats

    # ===================================================================
    #  ÜRÜNLER
    # ===================================================================
    def list_products(self, q=None):
        conn = self._conn()
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT * FROM products WHERE name LIKE ? OR aciklama LIKE ? ORDER BY id DESC",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_product(self, pid):
        conn = self._conn()
        row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_product(self, *, name, aciklama, birim_fiyat, stok, kategori=""):
        self._exec(
            "INSERT INTO products(name, aciklama, birim_fiyat, stok, kategori) VALUES (?,?,?,?,?)",
            (name, aciklama, birim_fiyat, stok, kategori),
        )

    def update_product(self, pid, *, name, aciklama, birim_fiyat, stok, kategori=""):
        self._exec(
            "UPDATE products SET name=?, aciklama=?, birim_fiyat=?, stok=?, kategori=? WHERE id=?",
            (name, aciklama, birim_fiyat, stok, kategori, pid),
        )

    def delete_product(self, pid):
        return self._exec_safe("DELETE FROM products WHERE id = ?", (pid,))

    # ===================================================================
    #  MÜŞTERİLER
    # ===================================================================
    def list_customers(self, q=None):
        conn = self._conn()
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT * FROM customers WHERE unvan LIKE ? OR vergi_no LIKE ? OR eposta LIKE ? ORDER BY id DESC",
                (like, like, like),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_customer(self, cid):
        conn = self._conn()
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def customer_options(self):
        """Fatura formu için (id, unvan) listesi."""
        conn = self._conn()
        rows = conn.execute("SELECT id, unvan FROM customers ORDER BY unvan").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def create_customer(self, *, unvan, vergi_no, adres, telefon, eposta):
        self._exec(
            "INSERT INTO customers(unvan, vergi_no, adres, telefon, eposta) VALUES (?,?,?,?,?)",
            (unvan, vergi_no, adres, telefon, eposta),
        )

    def update_customer(self, cid, *, unvan, vergi_no, adres, telefon, eposta):
        self._exec(
            "UPDATE customers SET unvan=?, vergi_no=?, adres=?, telefon=?, eposta=? WHERE id=?",
            (unvan, vergi_no, adres, telefon, eposta, cid),
        )

    def delete_customer(self, cid):
        return self._exec_safe("DELETE FROM customers WHERE id = ?", (cid,))

    # ===================================================================
    #  FATURALAR
    # ===================================================================
    def list_invoices(self, q=None, tip=None):
        conn = self._conn()
        base = """SELECT i.*, c.unvan AS musteri_unvan,
                         COALESCE((SELECT SUM(p.tutar) FROM payments p WHERE p.fatura_id = i.id), 0) AS odenen
                  FROM invoices i LEFT JOIN customers c ON c.id = i.musteri_id"""
        conditions = []
        params = []
        if tip == "teklif":
            conditions.append("i.fatura_tipi = 'Teklif'")
        elif tip:
            conditions.append("i.fatura_tipi != 'Teklif'")
        if q:
            like = f"%{q}%"
            conditions.append("(i.fatura_no LIKE ? OR c.unvan LIKE ?)")
            params.extend([like, like])
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = conn.execute(base + where + " ORDER BY i.id DESC", params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_invoice(self, iid):
        conn = self._conn()
        row = conn.execute(
            """SELECT i.*, c.unvan AS musteri_unvan, c.vergi_no, c.adres, c.telefon, c.eposta AS musteri_eposta
               FROM invoices i LEFT JOIN customers c ON c.id = i.musteri_id WHERE i.id = ?""",
            (iid,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_invoice(self, data):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO invoices(musteri_id, fatura_no, tarih, urun_kodu, acıklama,
                 Birim_Fiyat, iskonto, kdv, ara_toplam, iskonto_tutarı, kdv_tutarı,
                 toplam_tutar, fatura_tipi, vade_tarihi, gecerlilik_tarihi)
               VALUES (:musteri_id, :fatura_no, :tarih, :urun_kodu, :acıklama,
                 :Birim_Fiyat, :iskonto, :kdv, :ara_toplam, :iskonto_tutarı, :kdv_tutarı,
                 :toplam_tutar, :fatura_tipi, :vade_tarihi,
                 :gecerlilik_tarihi)""",
            {**data, "gecerlilik_tarihi": data.get("gecerlilik_tarihi", "")},
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return new_id

    def convert_teklif_to_invoice(self, iid, yeni_no):
        """Teklifin fatura_tipi'ni 'Satış' yapar ve yeni fatura_no atar."""
        self._exec(
            "UPDATE invoices SET fatura_tipi='Satış', fatura_no=? WHERE id=?",
            (yeni_no, iid),
        )

    def delete_invoice(self, iid):
        conn = self._conn()
        conn.execute("DELETE FROM payments WHERE fatura_id = ?", (iid,))
        conn.execute("DELETE FROM invoices WHERE id = ?", (iid,))
        conn.commit()
        conn.close()

    def next_invoice_no(self):
        """FAT2026000001 gibi otomatik fatura no üretir."""
        from datetime import datetime as _dt
        yil = _dt.now().year
        n = self._scalar("SELECT COUNT(*) FROM invoices") + 1
        return f"FAT{yil}{n:06d}"

    # ===================================================================
    #  ÖDEMELER
    # ===================================================================
    def list_payments(self):
        conn = self._conn()
        rows = conn.execute(
            """SELECT p.*, i.fatura_no, c.unvan AS musteri_unvan
               FROM payments p
               LEFT JOIN invoices i ON i.id = p.fatura_id
               LEFT JOIN customers c ON c.id = i.musteri_id
               ORDER BY p.id DESC"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_payment(self, pid):
        conn = self._conn()
        row = conn.execute("SELECT * FROM payments WHERE id = ?", (pid,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def invoice_options(self):
        """Ödeme formu için faturalar + kalan tutar."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT i.id, i.fatura_no, i.toplam_tutar, c.unvan AS musteri_unvan,
                      COALESCE((SELECT SUM(p.tutar) FROM payments p WHERE p.fatura_id = i.id),0) AS odenen
               FROM invoices i LEFT JOIN customers c ON c.id = i.musteri_id
               ORDER BY i.id DESC"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def create_payment(self, *, fatura_id, odeme_tarihi, tutar, odeme_tipi):
        self._exec(
            "INSERT INTO payments(fatura_id, odeme_tarihi, tutar, odeme_tipi) VALUES (?,?,?,?)",
            (fatura_id, odeme_tarihi, tutar, odeme_tipi),
        )

    def delete_payment(self, pid):
        self._exec("DELETE FROM payments WHERE id = ?", (pid,))

    # ===================================================================
    #  RAPORLAR (dashboard grafikleri)
    # ===================================================================
    def monthly_revenue(self, months=6):
        """Son N ayın satış cirosu — [{'ay':'2026-06','tutar':1234}, ...]."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT substr(tarih,1,7) AS ay, COALESCE(SUM(toplam_tutar),0) AS tutar
               FROM invoices WHERE fatura_tipi='Satış' AND tarih IS NOT NULL
               GROUP BY ay ORDER BY ay DESC LIMIT ?""",
            (months,),
        ).fetchall()
        conn.close()
        return list(reversed([dict(r) for r in rows]))

    def top_customers(self, limit=5):
        conn = self._conn()
        rows = conn.execute(
            """SELECT c.unvan, COALESCE(SUM(i.toplam_tutar),0) AS toplam
               FROM invoices i JOIN customers c ON c.id = i.musteri_id
               WHERE i.fatura_tipi='Satış'
               GROUP BY c.id ORDER BY toplam DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def recent_invoices(self, limit=5):
        conn = self._conn()
        rows = conn.execute(
            """SELECT i.fatura_no, i.tarih, i.toplam_tutar, i.fatura_tipi, c.unvan AS musteri_unvan
               FROM invoices i LEFT JOIN customers c ON c.id = i.musteri_id
               ORDER BY i.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ===================================================================
    #  GİDERLER
    # ===================================================================
    def list_expenses(self, q=None):
        conn = self._conn()
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT * FROM expenses WHERE kategori LIKE ? OR aciklama LIKE ? ORDER BY date(tarih) DESC, id DESC",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM expenses ORDER BY date(tarih) DESC, id DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_expense(self, eid):
        conn = self._conn()
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (eid,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_expense(self, *, tarih, kategori, aciklama, tutar, odeme_tipi):
        self._exec(
            "INSERT INTO expenses(tarih, kategori, aciklama, tutar, odeme_tipi, olusturulma) VALUES (?,?,?,?,?,?)",
            (tarih, kategori, aciklama, tutar, odeme_tipi,
             datetime.now().isoformat(timespec="seconds")),
        )

    def update_expense(self, eid, *, tarih, kategori, aciklama, tutar, odeme_tipi):
        self._exec(
            "UPDATE expenses SET tarih=?, kategori=?, aciklama=?, tutar=?, odeme_tipi=? WHERE id=?",
            (tarih, kategori, aciklama, tutar, odeme_tipi, eid),
        )

    def delete_expense(self, eid):
        self._exec("DELETE FROM expenses WHERE id = ?", (eid,))

    def total_expenses(self):
        return self._scalar("SELECT COALESCE(SUM(tutar),0) FROM expenses") or 0

    # ===================================================================
    #  AYARLAR (anahtar/değer)
    # ===================================================================
    def get_setting(self, anahtar, default=None):
        conn = self._conn()
        row = conn.execute("SELECT deger FROM settings WHERE anahtar = ?", (anahtar,)).fetchone()
        conn.close()
        return row["deger"] if row else default

    def all_settings(self):
        conn = self._conn()
        rows = conn.execute("SELECT anahtar, deger FROM settings").fetchall()
        conn.close()
        return {r["anahtar"]: r["deger"] for r in rows}

    def set_setting(self, anahtar, deger):
        self._exec(
            "INSERT INTO settings(anahtar, deger) VALUES (?,?) "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
            (anahtar, deger),
        )

    # ===================================================================
    #  RAPORLAR & ANALİZ
    # ===================================================================
    def kdv_summary(self, start=None, end=None):
        """Satış (tahsil edilen) ve alış (indirilecek) KDV özeti."""
        conn = self._conn()
        where, params = self._date_where("tarih", start, end)
        row = conn.execute(
            f"""SELECT
                  COALESCE(SUM(CASE WHEN fatura_tipi='Satış' THEN kdv_tutarı END),0) AS hesaplanan,
                  COALESCE(SUM(CASE WHEN fatura_tipi!='Satış' THEN kdv_tutarı END),0) AS indirilecek
                FROM invoices {where}""",
            params,
        ).fetchone()
        conn.close()
        hes = row["hesaplanan"] or 0
        ind = row["indirilecek"] or 0
        return {"hesaplanan": hes, "indirilecek": ind, "odenecek": round(hes - ind, 2)}

    def income_expense(self, start=None, end=None):
        """Gelir (satış faturaları), alış ve gider toplamları + kâr."""
        conn = self._conn()
        w_inv, p_inv = self._date_where("tarih", start, end)
        gelir = conn.execute(
            f"SELECT COALESCE(SUM(toplam_tutar),0) FROM invoices {w_inv}{' AND' if w_inv else ' WHERE'} fatura_tipi='Satış'",
            p_inv,
        ).fetchone()[0] or 0
        alis = conn.execute(
            f"SELECT COALESCE(SUM(toplam_tutar),0) FROM invoices {w_inv}{' AND' if w_inv else ' WHERE'} fatura_tipi!='Satış'",
            p_inv,
        ).fetchone()[0] or 0
        w_exp, p_exp = self._date_where("tarih", start, end)
        gider = conn.execute(
            f"SELECT COALESCE(SUM(tutar),0) FROM expenses {w_exp}", p_exp
        ).fetchone()[0] or 0
        conn.close()
        return {
            "gelir": gelir, "alis": alis, "gider": gider,
            "kar": round(gelir - alis - gider, 2),
        }

    def receivables_aging(self):
        """Vadesi geçen / yaklaşan alacaklar — açık bakiyeli satış faturaları."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT i.id, i.fatura_no, i.tarih, i.vade_tarihi, i.toplam_tutar,
                      c.unvan AS musteri_unvan,
                      COALESCE((SELECT SUM(p.tutar) FROM payments p WHERE p.fatura_id=i.id),0) AS odenen
               FROM invoices i LEFT JOIN customers c ON c.id=i.musteri_id
               WHERE i.fatura_tipi='Satış'
               ORDER BY date(i.vade_tarihi) ASC"""
        ).fetchall()
        conn.close()
        out = []
        bugun = datetime.now().date()
        for r in rows:
            d = dict(r)
            kalan = round((d["toplam_tutar"] or 0) - (d["odenen"] or 0), 2)
            if kalan <= 0.01:
                continue
            gun = None
            if d.get("vade_tarihi"):
                try:
                    vade = datetime.fromisoformat(d["vade_tarihi"][:10]).date()
                    gun = (bugun - vade).days  # +ise gecikmiş
                except ValueError:
                    gun = None
            d["kalan"] = kalan
            d["gecikme_gun"] = gun
            out.append(d)
        return out

    def top_products(self, limit=5, start=None, end=None):
        """En çok ciro getiren ürün kodları (satış faturalarından)."""
        conn = self._conn()
        where, params = self._date_where("tarih", start, end)
        cond = f"{where}{' AND' if where else ' WHERE'} fatura_tipi='Satış' AND urun_kodu IS NOT NULL AND urun_kodu!=''"
        rows = conn.execute(
            f"""SELECT urun_kodu, COUNT(*) AS adet, COALESCE(SUM(toplam_tutar),0) AS toplam
                FROM invoices {cond}
                GROUP BY urun_kodu ORDER BY toplam DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def low_stock_products(self, threshold=5):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM products WHERE stok <= ? ORDER BY stok ASC", (threshold,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def customer_statement(self, cid):
        """Müşteri cari ekstresi: faturalar (borç) + ödemeler (alacak), kronolojik."""
        conn = self._conn()
        inv = conn.execute(
            """SELECT id, tarih, fatura_no, fatura_tipi, toplam_tutar
               FROM invoices WHERE musteri_id = ?""",
            (cid,),
        ).fetchall()
        pay = conn.execute(
            """SELECT p.odeme_tarihi AS tarih, p.tutar, p.odeme_tipi, i.fatura_no
               FROM payments p JOIN invoices i ON i.id = p.fatura_id
               WHERE i.musteri_id = ?""",
            (cid,),
        ).fetchall()
        conn.close()

        hareketler = []
        for r in inv:
            d = dict(r)
            borc = (d["toplam_tutar"] or 0) if d["fatura_tipi"] == "Satış" else 0
            hareketler.append({
                "tarih": d["tarih"] or "", "aciklama": f"Fatura {d['fatura_no']}",
                "tip": d["fatura_tipi"], "borc": borc, "alacak": 0,
            })
        for r in pay:
            d = dict(r)
            hareketler.append({
                "tarih": d["tarih"] or "", "aciklama": f"Ödeme ({d['odeme_tipi'] or '—'}) · {d['fatura_no']}",
                "tip": "Ödeme", "borc": 0, "alacak": d["tutar"] or 0,
            })
        hareketler.sort(key=lambda x: (x["tarih"] or ""))
        bakiye = 0
        for h in hareketler:
            bakiye += h["borc"] - h["alacak"]
            h["bakiye"] = round(bakiye, 2)
        return hareketler

    @staticmethod
    def _date_where(col, start, end):
        clauses, params = [], []
        if start:
            clauses.append(f"date({col}) >= date(?)")
            params.append(start)
        if end:
            clauses.append(f"date({col}) <= date(?)")
            params.append(end)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    # ===================================================================
    #  DESTEK TALEPLERİ
    # ===================================================================
    def create_ticket(self, user_id, konu, mesaj):
        self._exec(
            "INSERT INTO destek_talepleri(user_id, konu, mesaj) VALUES (?,?,?)",
            (user_id, konu, mesaj),
        )

    def list_tickets(self, user_id=None):
        conn = self._conn()
        if user_id:
            rows = conn.execute(
                """SELECT t.*, u.name AS kullanici FROM destek_talepleri t
                   LEFT JOIN users u ON u.id = t.user_id
                   WHERE t.user_id = ? ORDER BY t.id DESC""",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT t.*, u.name AS kullanici FROM destek_talepleri t
                   LEFT JOIN users u ON u.id = t.user_id
                   ORDER BY t.id DESC""",
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def close_ticket(self, tid):
        self._exec("UPDATE destek_talepleri SET durum='kapali' WHERE id=?", (tid,))

    # ----- Yardımcılar -------------------------------------------------
    def _scalar(self, sql, params=()):
        conn = self._conn()
        val = conn.execute(sql, params).fetchone()[0]
        conn.close()
        return val

    def _exec(self, sql, params=()):
        conn = self._conn()
        conn.execute(sql, params)
        conn.commit()
        conn.close()

    def _exec_safe(self, sql, params=()):
        """Foreign key kısıtı gibi hataları yutar; başarı durumunu döndürür."""
        conn = self._conn()
        try:
            conn.execute(sql, params)
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    # ===================================================================
    #  TEDARİKÇİLER
    # ===================================================================
    def list_suppliers(self, q=None):
        conn = self._conn()
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT * FROM tedarikcilar WHERE unvan LIKE ? OR vergi_no LIKE ? OR eposta LIKE ? ORDER BY id DESC",
                (like, like, like),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tedarikcilar ORDER BY unvan").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_supplier(self, sid):
        conn = self._conn()
        row = conn.execute("SELECT * FROM tedarikcilar WHERE id = ?", (sid,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_supplier(self, *, unvan, vergi_no, adres, telefon, eposta, notlar):
        self._exec(
            "INSERT INTO tedarikcilar(unvan,vergi_no,adres,telefon,eposta,notlar,olusturulma) VALUES(?,?,?,?,?,?,?)",
            (unvan, vergi_no, adres, telefon, eposta, notlar,
             datetime.now().isoformat(timespec="seconds")),
        )

    def update_supplier(self, sid, *, unvan, vergi_no, adres, telefon, eposta, notlar):
        self._exec(
            "UPDATE tedarikcilar SET unvan=?,vergi_no=?,adres=?,telefon=?,eposta=?,notlar=? WHERE id=?",
            (unvan, vergi_no, adres, telefon, eposta, notlar, sid),
        )

    def delete_supplier(self, sid):
        self._exec("DELETE FROM tedarikcilar WHERE id=?", (sid,))

    def count_suppliers(self):
        return self._scalar("SELECT COUNT(*) FROM tedarikcilar")

    # ===================================================================
    #  KASA / BANKA HESAPLARI
    # ===================================================================
    def list_accounts(self):
        conn = self._conn()
        rows = conn.execute("SELECT * FROM hesaplar WHERE aktif=1 ORDER BY tur,ad").fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["bakiye"] = self.account_balance(d["id"])
            result.append(d)
        return result

    def get_account(self, aid):
        conn = self._conn()
        row = conn.execute("SELECT * FROM hesaplar WHERE id=?", (aid,)).fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        d["bakiye"] = self.account_balance(aid)
        return d

    def account_balance(self, aid):
        conn = self._conn()
        row = conn.execute("SELECT bakiye_baslangic FROM hesaplar WHERE id=?", (aid,)).fetchone()
        if not row:
            conn.close()
            return 0
        baslangic = row[0] or 0
        hareketler = conn.execute(
            "SELECT COALESCE(SUM(tutar),0) FROM hesap_hareketleri WHERE hesap_id=?", (aid,)
        ).fetchone()[0] or 0
        conn.close()
        return round(baslangic + hareketler, 2)

    def create_account(self, *, ad, tur, para_birimi, bakiye_baslangic, aciklama):
        self._exec(
            "INSERT INTO hesaplar(ad,tur,para_birimi,bakiye_baslangic,aciklama) VALUES(?,?,?,?,?)",
            (ad, tur, para_birimi, bakiye_baslangic, aciklama),
        )

    def update_account(self, aid, *, ad, tur, aciklama):
        self._exec("UPDATE hesaplar SET ad=?,tur=?,aciklama=? WHERE id=?", (ad, tur, aciklama, aid))

    def delete_account(self, aid):
        self._exec("DELETE FROM hesaplar WHERE id=?", (aid,))

    def list_account_movements(self, aid):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM hesap_hareketleri WHERE hesap_id=? ORDER BY tarih DESC,id DESC",
            (aid,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_movement(self, *, hesap_id, tarih, aciklama, tutar, tip, referans=""):
        self._exec(
            "INSERT INTO hesap_hareketleri(hesap_id,tarih,aciklama,tutar,tip,referans,olusturulma) VALUES(?,?,?,?,?,?,?)",
            (hesap_id, tarih, aciklama, tutar, tip, referans,
             datetime.now().isoformat(timespec="seconds")),
        )

    # ===================================================================
    #  ÇEK / SENET
    # ===================================================================
    def list_checks(self, tur=None, durum=None):
        conn = self._conn()
        clauses, params = [], []
        if tur:
            clauses.append("tur=?"); params.append(tur)
        if durum:
            clauses.append("durum=?"); params.append(durum)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM cek_senet{where} ORDER BY vade_tarihi ASC", params
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_check(self, cid):
        conn = self._conn()
        row = conn.execute("SELECT * FROM cek_senet WHERE id=?", (cid,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_check(self, *, tur, taraf, tutar, vade_tarihi, durum, notlar):
        self._exec(
            "INSERT INTO cek_senet(tur,taraf,tutar,vade_tarihi,durum,notlar,olusturulma) VALUES(?,?,?,?,?,?,?)",
            (tur, taraf, tutar, vade_tarihi, durum, notlar,
             datetime.now().isoformat(timespec="seconds")),
        )

    def update_check(self, cid, *, tur, taraf, tutar, vade_tarihi, durum, notlar):
        self._exec(
            "UPDATE cek_senet SET tur=?,taraf=?,tutar=?,vade_tarihi=?,durum=?,notlar=? WHERE id=?",
            (tur, taraf, tutar, vade_tarihi, durum, notlar, cid),
        )

    def set_check_status(self, cid, durum):
        self._exec("UPDATE cek_senet SET durum=? WHERE id=?", (durum, cid))

    def delete_check(self, cid):
        self._exec("DELETE FROM cek_senet WHERE id=?", (cid,))

    # ===================================================================
    #  STOK HAREKETLERİ
    # ===================================================================
    def list_stock_movements(self, pid=None):
        conn = self._conn()
        if pid:
            rows = conn.execute(
                "SELECT s.*, p.name AS urun_adi FROM stok_hareketleri s "
                "JOIN products p ON p.id=s.urun_id WHERE s.urun_id=? ORDER BY s.id DESC",
                (pid,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT s.*, p.name AS urun_adi FROM stok_hareketleri s "
                "JOIN products p ON p.id=s.urun_id ORDER BY s.id DESC LIMIT 200"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_stock_movement(self, *, urun_id, tur, miktar, aciklama="", referans=""):
        self._exec(
            "INSERT INTO stok_hareketleri(urun_id,tur,miktar,aciklama,referans,olusturulma) VALUES(?,?,?,?,?,?)",
            (urun_id, tur, miktar, aciklama, referans,
             datetime.now().isoformat(timespec="seconds")),
        )
        # Stok güncelle
        delta = miktar if tur == "Giriş" else -miktar
        self._exec("UPDATE products SET stok = stok + ? WHERE id=?", (delta, urun_id))

    # ===================================================================
    #  BÜTÇE
    # ===================================================================
    def list_budgets(self, yil, ay):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM butce WHERE yil=? AND ay=? ORDER BY kategori", (yil, ay)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def set_budget(self, yil, ay, kategori, hedef_tutar):
        self._exec(
            "INSERT INTO butce(yil,ay,kategori,hedef_tutar) VALUES(?,?,?,?) "
            "ON CONFLICT(yil,ay,kategori) DO UPDATE SET hedef_tutar=excluded.hedef_tutar",
            (yil, ay, kategori, hedef_tutar),
        )

    def budget_actual(self, yil, ay):
        """O ay gerçekleşen giderler — kategori bazlı."""
        ay_str = f"{yil:04d}-{ay:02d}"
        conn = self._conn()
        rows = conn.execute(
            "SELECT kategori, COALESCE(SUM(tutar),0) AS toplam FROM expenses "
            "WHERE substr(tarih,1,7)=? GROUP BY kategori",
            (ay_str,),
        ).fetchall()
        conn.close()
        return {r["kategori"]: r["toplam"] for r in rows}

    # ===================================================================
    #  DENETİM KAYDI (AUDIT LOG)
    # ===================================================================
    def add_audit_log(self, *, kullanici_id, kullanici_adi, islem, tablo, kayit_id=None, detay=""):
        self._exec(
            "INSERT INTO audit_log(kullanici_id,kullanici_adi,islem,tablo,kayit_id,detay,tarih) VALUES(?,?,?,?,?,?,?)",
            (kullanici_id, kullanici_adi, islem, tablo, kayit_id, detay,
             datetime.now().isoformat(timespec="seconds")),
        )

    def list_audit_logs(self, limit=200):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ===================================================================
    #  TEKRARLAYAN FATURALAR
    # ===================================================================
    def list_recurring(self):
        conn = self._conn()
        rows = conn.execute(
            """SELECT r.*, c.unvan AS musteri_unvan FROM tekrarlayan_faturalar r
               LEFT JOIN customers c ON c.id=r.musteri_id ORDER BY r.id DESC"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def create_recurring(self, *, musteri_id, aciklama, tutar, kdv, periyot, sonraki_tarih):
        self._exec(
            "INSERT INTO tekrarlayan_faturalar(musteri_id,aciklama,tutar,kdv,periyot,sonraki_tarih,aktif,olusturulma) VALUES(?,?,?,?,?,?,1,?)",
            (musteri_id, aciklama, tutar, kdv, periyot, sonraki_tarih,
             datetime.now().isoformat(timespec="seconds")),
        )

    def get_recurring(self, rid):
        conn = self._conn()
        row = conn.execute(
            """SELECT r.*, c.unvan AS musteri_unvan FROM tekrarlayan_faturalar r
               LEFT JOIN customers c ON c.id=r.musteri_id WHERE r.id=?""",
            (rid,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def update_recurring(self, rid, *, musteri_id, aciklama, tutar, kdv, periyot, sonraki_tarih):
        self._exec(
            """UPDATE tekrarlayan_faturalar
               SET musteri_id=?, aciklama=?, tutar=?, kdv=?, periyot=?, sonraki_tarih=?
               WHERE id=?""",
            (musteri_id, aciklama, tutar, kdv, periyot, sonraki_tarih, rid),
        )

    def toggle_recurring(self, rid):
        conn = self._conn()
        row = conn.execute("SELECT aktif FROM tekrarlayan_faturalar WHERE id=?", (rid,)).fetchone()
        conn.close()
        if row:
            self._exec("UPDATE tekrarlayan_faturalar SET aktif=? WHERE id=?",
                       (0 if row[0] else 1, rid))

    def fire_recurring(self, rid):
        """Tekrarlayan faturadan yeni fatura oluşturur ve sonraki tarihi günceller."""
        conn = self._conn()
        r = conn.execute(
            "SELECT r.*, c.unvan AS musteri_unvan FROM tekrarlayan_faturalar r "
            "LEFT JOIN customers c ON c.id=r.musteri_id WHERE r.id=?", (rid,)
        ).fetchone()
        conn.close()
        if not r:
            return None
        r = dict(r)
        from datetime import date
        bugun = date.today().isoformat()
        tutar = r["tutar"] or 0
        kdv_oran = r["kdv"] or 20
        kdv_tutar = round(tutar * kdv_oran / 100, 2)
        toplam = round(tutar + kdv_tutar, 2)
        fatura_no = self.next_invoice_no()
        data = {
            "musteri_id": r["musteri_id"], "fatura_no": fatura_no,
            "tarih": bugun, "urun_kodu": "", "acıklama": r["aciklama"],
            "Birim_Fiyat": tutar, "iskonto": 0, "kdv": kdv_oran,
            "ara_toplam": tutar, "iskonto_tutarı": 0,
            "kdv_tutarı": kdv_tutar, "toplam_tutar": toplam,
            "fatura_tipi": "Satış", "vade_tarihi": bugun,
        }
        self.create_invoice(data)
        # Sonraki tarihi güncelle
        from datetime import timedelta
        periyot = r["periyot"]
        try:
            dt = datetime.fromisoformat(r["sonraki_tarih"]).date()
        except Exception:
            dt = date.today()
        if periyot == "Haftalık":
            dt = dt + timedelta(weeks=1)
        elif periyot == "Yıllık":
            dt = dt.replace(year=dt.year + 1)
        else:  # Aylık
            m = dt.month % 12 + 1
            y = dt.year + (1 if dt.month == 12 else 0)
            dt = dt.replace(year=y, month=m)
        self._exec("UPDATE tekrarlayan_faturalar SET sonraki_tarih=? WHERE id=?",
                   (dt.isoformat(), rid))
        return fatura_no

    def delete_recurring(self, rid):
        self._exec("DELETE FROM tekrarlayan_faturalar WHERE id=?", (rid,))

    # ===================================================================
    #  BİLDİRİM / DASHBOARD UYARILARI
    # ===================================================================
    def dashboard_alerts(self):
        """Vadesi geçen faturalar, düşük stok, bekleyen çekler."""
        from datetime import date
        bugun = date.today().isoformat()
        conn = self._conn()
        alerts = []

        # Vadesi geçmiş faturalar
        vadesi_gecmis = conn.execute(
            """SELECT COUNT(*) FROM invoices i WHERE fatura_tipi='Satış'
               AND vade_tarihi < ? AND vade_tarihi IS NOT NULL
               AND (SELECT COALESCE(SUM(p.tutar),0) FROM payments p WHERE p.fatura_id=i.id) < i.toplam_tutar""",
            (bugun,)
        ).fetchone()[0]
        if vadesi_gecmis:
            alerts.append({"tip": "danger", "ikon": "⏰",
                           "mesaj": f"{vadesi_gecmis} faturanın vadesi geçmiş",
                           "url": "/raporlar/"})

        # Düşük stok
        dusuk = conn.execute(
            "SELECT COUNT(*) FROM products WHERE stok <= 5"
        ).fetchone()[0]
        if dusuk:
            alerts.append({"tip": "warning", "ikon": "📦",
                           "mesaj": f"{dusuk} ürün düşük stokta (≤5 adet)",
                           "url": "/urunler/"})

        # Bekleyen çekler (7 gün içinde vadeli)
        from datetime import timedelta
        yedi_gun = (date.today() + timedelta(days=7)).isoformat()
        bekleyen_cek = conn.execute(
            "SELECT COUNT(*) FROM cek_senet WHERE durum='Beklemede' AND vade_tarihi <= ?",
            (yedi_gun,)
        ).fetchone()[0]
        if bekleyen_cek:
            alerts.append({"tip": "info", "ikon": "🏦",
                           "mesaj": f"{bekleyen_cek} çek/senet 7 gün içinde vadeli",
                           "url": "/cek-senet/"})

        conn.close()
        return alerts

    # ===================================================================
    #  YENİ RAPORLAR
    # ===================================================================
    def cash_flow_forecast(self, days=90):
        """Önümüzdeki N gün için nakit akışı tahmini (açık faturalar + gider ortalaması)."""
        from datetime import date, timedelta
        bugun = date.today()
        conn = self._conn()

        # Açık alacaklar (vadeli)
        alacaklar = conn.execute(
            """SELECT vade_tarihi, COALESCE(SUM(toplam_tutar),0) - COALESCE(
                (SELECT SUM(p.tutar) FROM payments p WHERE p.fatura_id=i.id),0) AS kalan
               FROM invoices i WHERE fatura_tipi='Satış' AND vade_tarihi IS NOT NULL
               GROUP BY vade_tarihi HAVING kalan > 0"""
        ).fetchall()

        # Son 3 ay ortalama gider
        uc_ay_once = (bugun - timedelta(days=90)).isoformat()
        aylik_gider = conn.execute(
            "SELECT COALESCE(SUM(tutar),0)/3.0 FROM expenses WHERE tarih >= ?",
            (uc_ay_once,)
        ).fetchone()[0] or 0
        conn.close()

        # Aylık tahmin oluştur
        forecast = {}
        for i in range(days):
            gun = bugun + timedelta(days=i)
            ay_key = gun.strftime("%Y-%m")
            forecast.setdefault(ay_key, {"gelir": 0, "gider": 0})

        for r in alacaklar:
            try:
                vade = datetime.fromisoformat(r["vade_tarihi"][:10]).date()
                if bugun <= vade <= bugun + timedelta(days=days):
                    ay_key = vade.strftime("%Y-%m")
                    if ay_key in forecast:
                        forecast[ay_key]["gelir"] += r["kalan"]
            except Exception:
                pass

        for ay_key in forecast:
            forecast[ay_key]["gider"] = round(aylik_gider, 2)

        return [{"ay": k, **v, "net": round(v["gelir"] - v["gider"], 2)}
                for k, v in sorted(forecast.items())]

    def balance_sheet(self):
        """Basit bilanço: varlıklar ve yükümlülükler."""
        conn = self._conn()
        # Varlıklar
        kasa_banka = sum(self.account_balance(r["id"])
                         for r in conn.execute("SELECT id FROM hesaplar WHERE aktif=1").fetchall())
        alacaklar = conn.execute(
            """SELECT COALESCE(SUM(i.toplam_tutar),0) -
               COALESCE((SELECT SUM(p.tutar) FROM payments p),0) FROM invoices i
               WHERE fatura_tipi='Satış'"""
        ).fetchone()[0] or 0
        stok_degeri = conn.execute(
            "SELECT COALESCE(SUM(birim_fiyat*stok),0) FROM products"
        ).fetchone()[0] or 0

        # Yükümlülükler
        borclar = conn.execute(
            """SELECT COALESCE(SUM(toplam_tutar),0) FROM invoices WHERE fatura_tipi='Alış'"""
        ).fetchone()[0] or 0
        conn.close()

        toplam_varlik = round(kasa_banka + alacaklar + stok_degeri, 2)
        toplam_borclar = round(borclar, 2)
        oz_kaynak = round(toplam_varlik - toplam_borclar, 2)

        return {
            "kasa_banka": round(kasa_banka, 2),
            "alacaklar": round(alacaklar, 2),
            "stok": round(stok_degeri, 2),
            "toplam_varlik": toplam_varlik,
            "borclar": toplam_borclar,
            "oz_kaynak": oz_kaynak,
        }

    def period_comparison(self, yil=None, ay=None):
        """Bu ay vs. geçen ay vs. geçen yıl aynı ay."""
        from datetime import date
        if not yil or not ay:
            bugun = date.today()
            yil, ay = bugun.year, bugun.month
        bu_ay = f"{yil:04d}-{ay:02d}"
        gecen_ay_dt = date(yil, ay, 1)
        if ay == 1:
            gecen_ay = f"{yil-1:04d}-12"
        else:
            gecen_ay = f"{yil:04d}-{ay-1:02d}"
        gecen_yil_ay = f"{yil-1:04d}-{ay:02d}"

        def ay_gelir(ay_str):
            return self._scalar(
                "SELECT COALESCE(SUM(toplam_tutar),0) FROM invoices "
                "WHERE fatura_tipi='Satış' AND substr(tarih,1,7)=?", (ay_str,)
            ) or 0

        def ay_gider(ay_str):
            return self._scalar(
                "SELECT COALESCE(SUM(tutar),0) FROM expenses WHERE substr(tarih,1,7)=?",
                (ay_str,)
            ) or 0

        return {
            "bu_ay":       {"ay": bu_ay,       "gelir": ay_gelir(bu_ay),       "gider": ay_gider(bu_ay)},
            "gecen_ay":    {"ay": gecen_ay,     "gelir": ay_gelir(gecen_ay),    "gider": ay_gider(gecen_ay)},
            "gecen_yil":   {"ay": gecen_yil_ay, "gelir": ay_gelir(gecen_yil_ay),"gider": ay_gider(gecen_yil_ay)},
        }

    def customer_profitability(self, limit=10):
        """Müşteri bazlı ciro, ödenen ve kâr marjı."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT c.id, c.unvan,
               COALESCE(SUM(i.toplam_tutar),0) AS ciro,
               COALESCE((SELECT SUM(p.tutar) FROM payments p
                         JOIN invoices ii ON ii.id=p.fatura_id
                         WHERE ii.musteri_id=c.id),0) AS odenen,
               COUNT(i.id) AS fatura_sayisi
               FROM customers c
               LEFT JOIN invoices i ON i.musteri_id=c.id AND i.fatura_tipi='Satış'
               GROUP BY c.id ORDER BY ciro DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["kalan"] = round(d["ciro"] - d["odenen"], 2)
            result.append(d)
        return result

    # ----- Bildirim Log ------------------------------------------------
    def bildirim_gonderildi_mi(self, user_id: int, tip: str, referans: str) -> bool:
        """Bu bildirim daha önce gönderildi mi?"""
        conn = self._conn()
        row = conn.execute(
            "SELECT 1 FROM bildirim_log WHERE user_id=? AND tip=? AND referans=?",
            (user_id, tip, referans),
        ).fetchone()
        conn.close()
        return row is not None

    def bildirim_logla(self, user_id: int, tip: str, referans: str):
        """Bildirimi gönderildi olarak işaretle."""
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO bildirim_log(user_id, tip, referans) VALUES(?,?,?)",
            (user_id, tip, referans),
        )
        conn.commit()
        conn.close()

    # ----- FCM Push Token'ları ------------------------------------------
    def save_fcm_token(self, user_id: int, token: str):
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO fcm_tokens(user_id, token, olusturulma) "
            "VALUES(?, ?, datetime('now'))",
            (user_id, token),
        )
        conn.commit()
        conn.close()

    def delete_fcm_token(self, token: str):
        conn = self._conn()
        conn.execute("DELETE FROM fcm_tokens WHERE token = ?", (token,))
        conn.commit()
        conn.close()

    def get_user_fcm_tokens(self, user_id: int):
        conn = self._conn()
        rows = conn.execute(
            "SELECT token FROM fcm_tokens WHERE user_id = ?", (user_id,)
        ).fetchall()
        conn.close()
        return [r["token"] for r in rows]

    def get_all_fcm_tokens(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT user_id, token FROM fcm_tokens"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Fabrika — uygulama genelinde tek erişim noktası
# ---------------------------------------------------------------------------
def get_repo():
    """İstek başına repository nesnesi döndürür (Flask g üzerinde cache'lenir)."""
    if "repo" not in g:
        backend = current_app.config.get("DATA_BACKEND", "sqlite")
        if backend == "firebase":
            # Geçişte: from .firebase_repo import FirebaseRepository
            raise NotImplementedError("Firebase backend henüz eklenmedi.")
        g.repo = SqliteRepository(current_app.config["SQLITE_PATH"])
    return g.repo
