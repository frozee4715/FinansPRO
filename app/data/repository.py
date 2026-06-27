"""
Repository deseni — SQLite uygulaması.

Tek bir arayüz (SqliteRepository) tüm CRUD işlemlerini sağlar. Firebase'e
geçişte aynı metod imzalarına sahip FirebaseRepository yazılır ve
get_repo() onu döndürür.
"""
import re
import sqlite3
from datetime import datetime, timedelta
from flask import current_app, g

try:
    import psycopg                          # PostgreSQL sürücüsü (production)
except ImportError:                         # lokal geliştirmede gerekmeyebilir
    psycopg = None


# ===========================================================================
# Dialect katmanı — aynı kod hem SQLite (lokal) hem PostgreSQL (production)
# ---------------------------------------------------------------------------
# DATABASE_URL doluysa Postgres, boşsa SQLite kullanılır. SQLite '?' ve ':isim'
# placeholder'larını psycopg'nin '%s' / '%(isim)s' biçimine çeviririz; satırlar
# sqlite3.Row gibi hem indeks (row[0]) hem anahtar (row['kol']) erişimi sunar.
# ===========================================================================
# ':isim' yakalar ama '::date' cast'ine dokunmaz (lookbehind ile).
_NAMED_RE = re.compile(r"(?<!:):(\w+)")


def _translate(sql):
    """SQLite placeholder'larını psycopg biçimine çevirir."""
    sql = _NAMED_RE.sub(r"%(\1)s", sql)     # :isim  -> %(isim)s
    sql = sql.replace("?", "%s")            # ?      -> %s
    return sql


class _Row:
    """Hem indeks hem anahtar erişimli satır (sqlite3.Row taklidi)."""
    __slots__ = ("_m", "_v")

    def __init__(self, cols, vals):
        self._v = tuple(vals)
        self._m = {c: i for i, c in enumerate(cols)}

    def __getitem__(self, k):
        return self._v[k] if isinstance(k, int) else self._v[self._m[k]]

    def get(self, k, d=None):
        i = self._m.get(k)
        return self._v[i] if i is not None else d

    def keys(self):
        return list(self._m.keys())

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return len(self._v)


def _pg_rowf(cur):
    cols = [d.name for d in (cur.description or [])]

    def make(vals):
        return _Row(cols, vals)
    return make


class _PgCursor:
    """psycopg cursor'ı sqlite3 alışkanlıklarına uyarlar (?, fetchone vb.)."""
    def __init__(self, cur):
        self._c = cur

    @property
    def lastrowid(self):                    # Postgres'te RETURNING kullanılır
        return None

    def execute(self, sql, params=None):
        self._c.execute(_translate(sql), params)
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def close(self):
        self._c.close()


class _PgConn:
    """psycopg connection'ı sqlite3 Connection arayüzüne benzetir."""
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=None):
        cur = self._raw.cursor()
        cur.execute(_translate(sql), params)
        return cur                          # psycopg cursor fetchone/fetchall destekler

    def cursor(self):
        return _PgCursor(self._raw.cursor())

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


# ---------------------------------------------------------------------------
# Bağlantı yönetimi
# ---------------------------------------------------------------------------
def _connect(url, path):
    if url:
        if psycopg is None:
            raise RuntimeError("psycopg kurulu değil ama DATABASE_URL verilmiş.")
        raw = psycopg.connect(url, row_factory=_pg_rowf, autocommit=False)
        return _PgConn(raw)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row          # sözlük benzeri satır erişimi
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ddl(sql, is_pg):
    """Şema (DDL) ifadesini hedef motora uyarlar."""
    if not is_pg:
        return sql
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    sql = sql.replace("DEFAULT CURRENT_TIMESTAMP", "DEFAULT (now()::text)")
    return sql


def _is_integrity_error(e):
    """Hata bir bütünlük (FK/UNIQUE) ihlali mi? İki motoru da kapsar."""
    if isinstance(e, sqlite3.IntegrityError):
        return True
    if psycopg is not None and isinstance(e, psycopg.IntegrityError):
        return True
    return False


# ---------------------------------------------------------------------------
# Şema kurulumu / göçü
# ---------------------------------------------------------------------------
def init_schema(cfg):
    """Tabloları ve web için gereken yeni sütunları oluşturur (idempotent).

    cfg: app.config benzeri; DATABASE_URL (varsa Postgres) ve SQLITE_PATH içerir.
    """
    url = cfg.get("DATABASE_URL", "")
    path = cfg["SQLITE_PATH"]
    is_pg = bool(url)
    conn = _connect(url, path)
    cur = conn.cursor()

    def ddl(sql):
        cur.execute(_ddl(sql, is_pg))

    # Mevcut CLI tablolarıyla uyumlu temel tablolar
    ddl("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, age INTEGER, eposta TEXT, sifre TEXT, yetki TEXT)""")
    ddl("""CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unvan TEXT, vergi_no TEXT, adres TEXT, telefon TEXT, eposta TEXT)""")
    ddl("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, aciklama TEXT, birim_fiyat REAL, stok INTEGER)""")
    # invoices: 'Birim_Fiyat' büyük harfli → iki motorda da aynı kalsın diye tırnaklı
    ddl("""CREATE TABLE IF NOT EXISTS invoices(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        musteri_id INTEGER, fatura_no TEXT, tarih TEXT, urun_kodu TEXT,
        acıklama TEXT, "Birim_Fiyat" REAL, iskonto REAL, kdv REAL,
        ara_toplam REAL, iskonto_tutarı REAL, kdv_tutarı REAL,
        toplam_tutar REAL, fatura_tipi TEXT, vade_tarihi TEXT,
        FOREIGN KEY(musteri_id) REFERENCES customers(id))""")
    ddl("""CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fatura_id INTEGER, odeme_tarihi TEXT, tutar REAL, odeme_tipi TEXT,
        FOREIGN KEY(fatura_id) REFERENCES invoices(id))""")

    # Giderler / masraflar
    ddl("""CREATE TABLE IF NOT EXISTS expenses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tarih TEXT, kategori TEXT, aciklama TEXT, tutar REAL, odeme_tipi TEXT,
        olusturulma TEXT)""")

    # Uygulama ayarları (anahtar/değer) — şirket bilgisi, plan, vb.
    ddl("""CREATE TABLE IF NOT EXISTS settings(
        anahtar TEXT PRIMARY KEY, deger TEXT)""")

    # Destek talepleri
    ddl("""CREATE TABLE IF NOT EXISTS destek_talepleri(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, konu TEXT, mesaj TEXT,
        durum TEXT DEFAULT 'acik',
        olusturma TEXT DEFAULT CURRENT_TIMESTAMP)""")

    # Tedarikçiler
    ddl("""CREATE TABLE IF NOT EXISTS tedarikcilar(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unvan TEXT, vergi_no TEXT, adres TEXT, telefon TEXT,
        eposta TEXT, notlar TEXT, olusturulma TEXT)""")

    # Kasa / Banka hesapları
    ddl("""CREATE TABLE IF NOT EXISTS hesaplar(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad TEXT, tur TEXT, para_birimi TEXT DEFAULT '₺',
        bakiye_baslangic REAL DEFAULT 0, aciklama TEXT, aktif INTEGER DEFAULT 1)""")
    ddl("""CREATE TABLE IF NOT EXISTS hesap_hareketleri(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hesap_id INTEGER, tarih TEXT, aciklama TEXT,
        tutar REAL, tip TEXT, referans TEXT,
        olusturulma TEXT,
        FOREIGN KEY(hesap_id) REFERENCES hesaplar(id))""")

    # Çek / Senet
    ddl("""CREATE TABLE IF NOT EXISTS cek_senet(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tur TEXT, taraf TEXT, tutar REAL,
        vade_tarihi TEXT, durum TEXT DEFAULT 'Beklemede',
        notlar TEXT, olusturulma TEXT)""")

    # Stok hareketleri
    ddl("""CREATE TABLE IF NOT EXISTS stok_hareketleri(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        urun_id INTEGER, tur TEXT, miktar INTEGER,
        aciklama TEXT, referans TEXT, olusturulma TEXT,
        FOREIGN KEY(urun_id) REFERENCES products(id))""")

    # Bütçe
    ddl("""CREATE TABLE IF NOT EXISTS butce(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        yil INTEGER, ay INTEGER, kategori TEXT,
        hedef_tutar REAL,
        UNIQUE(yil, ay, kategori))""")

    # Denetim kaydı
    ddl("""CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_id INTEGER, kullanici_adi TEXT,
        islem TEXT, tablo TEXT, kayit_id INTEGER,
        detay TEXT, tarih TEXT)""")

    # Tekrarlayan faturalar
    ddl("""CREATE TABLE IF NOT EXISTS tekrarlayan_faturalar(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        musteri_id INTEGER, aciklama TEXT, tutar REAL,
        kdv REAL DEFAULT 20, periyot TEXT,
        sonraki_tarih TEXT, aktif INTEGER DEFAULT 1,
        olusturulma TEXT)""")

    # Gönderilen bildirim kaydı (tekrar gönderimi önler)
    ddl("""CREATE TABLE IF NOT EXISTS bildirim_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        tip TEXT NOT NULL,
        referans TEXT NOT NULL,
        tarih TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, tip, referans))""")

    # FCM Push bildirim token'ları
    ddl("""CREATE TABLE IF NOT EXISTS fcm_tokens(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT NOT NULL UNIQUE,
        olusturulma TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)""")

    # AI yanıt önbelleği (token tasarrufu): aynı soru + aynı veri → API'ye gitmez
    ddl("""CREATE TABLE IF NOT EXISTS ai_cache(
        soru_hash TEXT PRIMARY KEY,
        soru TEXT, cevap TEXT, olusturma TEXT)""")

    # Web için users tablosuna eklenen sütunlar (varsa atlar)
    _add_column(cur, "users", "parola_hash", "TEXT", is_pg)
    _add_column(cur, "users", "rol", "TEXT DEFAULT 'kullanici'", is_pg)
    _add_column(cur, "users", "aktif", "INTEGER DEFAULT 1", is_pg)
    _add_column(cur, "users", "basarisiz_giris", "INTEGER DEFAULT 0", is_pg)
    _add_column(cur, "users", "kilit_bitis", "TEXT", is_pg)
    _add_column(cur, "users", "olusturulma", "TEXT", is_pg)
    _add_column(cur, "users", "son_giris", "TEXT", is_pg)
    _add_column(cur, "users", "plan", "TEXT DEFAULT 'free'", is_pg)

    # Mevcut tablolara yeni sütunlar
    _add_column(cur, "products", "kategori", "TEXT DEFAULT ''", is_pg)
    _add_column(cur, "invoices", "tur", "TEXT DEFAULT 'Fatura'", is_pg)
    _add_column(cur, "invoices", "gecerlilik_tarihi", "TEXT", is_pg)

    # --- ÇOK KİRACILI (multi-tenant) izolasyon: her iş tablosuna user_id -----
    # Her firmanın verisi yalnızca kendisine görünür; sorgular user_id ile filtrelenir.
    _ISCOPED = [
        "customers", "products", "invoices", "payments", "expenses",
        "tedarikcilar", "hesaplar", "hesap_hareketleri", "cek_senet",
        "stok_hareketleri", "butce", "tekrarlayan_faturalar",
    ]
    for t in _ISCOPED:
        _add_column(cur, t, "user_id", "INTEGER", is_pg)
        ddl(f"CREATE INDEX IF NOT EXISTS idx_{t}_user ON {t}(user_id)")

    # Kullanıcı bazlı ayarlar (şirket adı, marka vb. her firma için ayrı).
    # Eski global 'settings' tablosu yerine bunu kullanırız.
    ddl("""CREATE TABLE IF NOT EXISTS user_settings(
        user_id INTEGER NOT NULL,
        anahtar TEXT NOT NULL,
        deger TEXT,
        PRIMARY KEY(user_id, anahtar))""")

    # Kullanıcı bazlı bütçe (eski 'butce' tablosundaki UNIQUE(yil,ay,kategori)
    # çok firmaya uymuyor; bunun bileşik anahtarı user_id içerir).
    ddl("""CREATE TABLE IF NOT EXISTS user_butce(
        user_id INTEGER NOT NULL,
        yil INTEGER, ay INTEGER, kategori TEXT,
        hedef_tutar REAL,
        PRIMARY KEY(user_id, yil, ay, kategori))""")

    conn.commit()
    conn.close()


def _add_column(cur, table, column, decl, is_pg):
    if is_pg:
        # Postgres: IF NOT EXISTS yerleşik → istisnaya gerek yok
        cur.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {decl}')
        return
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    except sqlite3.OperationalError:
        pass  # sütun zaten var


# ---------------------------------------------------------------------------
# Repository (SQLite + PostgreSQL ortak)
# ---------------------------------------------------------------------------
class SqliteRepository:
    def __init__(self, url, path, uid=None):
        self.url = url
        self.path = path
        self.is_pg = bool(url)
        # Çok kiracılı izolasyon: geçerli kullanıcı (firma) id'si.
        # İş verisi sorguları yalnızca bu kullanıcının kayıtlarını görür/oluşturur.
        self.uid = uid

    def _conn(self):
        return _connect(self.url, self.path)

    def _date(self, expr):
        """Tarih kısmına indirger: SQLite date(x) / Postgres (x)::date."""
        return f"({expr})::date" if self.is_pg else f"date({expr})"

    def _now_sql(self):
        """Şu an (metin): SQLite datetime('now') / Postgres now()::text."""
        return "now()::text" if self.is_pg else "datetime('now')"

    def _insert_returning_id(self, conn, cur, sql, params):
        """INSERT yapıp yeni id'yi döndürür (Postgres RETURNING / SQLite lastrowid)."""
        if self.is_pg:
            cur.execute(sql.rstrip().rstrip(";") + " RETURNING id", params)
            new_id = cur.fetchone()[0]
            conn.commit()
        else:
            cur.execute(sql, params)
            conn.commit()
            new_id = cur.lastrowid
        return new_id

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
        sql = """INSERT INTO users(name, age, eposta, parola_hash, rol, yetki,
                                 aktif, basarisiz_giris, olusturulma)
               VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?)"""
        params = (name, age, eposta, parola_hash, rol, rol,
                  datetime.now().isoformat(timespec="seconds"))
        new_id = self._insert_returning_id(conn, cur, sql, params)
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

    def set_user_password(self, user_id, parola_hash):
        self._exec("UPDATE users SET parola_hash = ? WHERE id = ?", (parola_hash, user_id))

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

        def safe(sql, params=()):
            try:
                return c.execute(sql, params).fetchone()[0] or 0
            except Exception:
                # Postgres'te hatalı sorgu işlemi (transaction) bozar → geri al
                try:
                    conn.rollback()
                except Exception:
                    pass
                return 0

        u = (self.uid,)
        stats = {
            "musteri": safe("SELECT COUNT(*) FROM customers WHERE user_id = ?", u),
            "urun": safe("SELECT COUNT(*) FROM products WHERE user_id = ?", u),
            "fatura": safe("SELECT COUNT(*) FROM invoices WHERE user_id = ?", u),
            "ciro": safe("SELECT COALESCE(SUM(toplam_tutar),0) FROM invoices WHERE user_id = ? AND fatura_tipi='Satış'", u),
            "tahsilat": safe("SELECT COALESCE(SUM(tutar),0) FROM payments WHERE user_id = ?", u),
            "dusuk_stok": safe("SELECT COUNT(*) FROM products WHERE user_id = ? AND stok <= 5", u),
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
                "SELECT * FROM products WHERE user_id = ? AND (name LIKE ? OR aciklama LIKE ?) ORDER BY id DESC",
                (self.uid, like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM products WHERE user_id = ? ORDER BY id DESC", (self.uid,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_product(self, pid):
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM products WHERE id = ? AND user_id = ?", (pid, self.uid)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_product(self, *, name, aciklama, birim_fiyat, stok, kategori=""):
        self._exec(
            "INSERT INTO products(name, aciklama, birim_fiyat, stok, kategori, user_id) VALUES (?,?,?,?,?,?)",
            (name, aciklama, birim_fiyat, stok, kategori, self.uid),
        )

    def update_product(self, pid, *, name, aciklama, birim_fiyat, stok, kategori=""):
        self._exec(
            "UPDATE products SET name=?, aciklama=?, birim_fiyat=?, stok=?, kategori=? WHERE id=? AND user_id=?",
            (name, aciklama, birim_fiyat, stok, kategori, pid, self.uid),
        )

    def delete_product(self, pid):
        return self._exec_safe("DELETE FROM products WHERE id = ? AND user_id = ?", (pid, self.uid))

    # ===================================================================
    #  MÜŞTERİLER
    # ===================================================================
    def list_customers(self, q=None):
        conn = self._conn()
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT * FROM customers WHERE user_id = ? AND (unvan LIKE ? OR vergi_no LIKE ? OR eposta LIKE ?) ORDER BY id DESC",
                (self.uid, like, like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM customers WHERE user_id = ? ORDER BY id DESC", (self.uid,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_customer(self, cid):
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM customers WHERE id = ? AND user_id = ?", (cid, self.uid)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def customer_options(self):
        """Fatura formu için (id, unvan) listesi."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, unvan FROM customers WHERE user_id = ? ORDER BY unvan", (self.uid,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def create_customer(self, *, unvan, vergi_no, adres, telefon, eposta):
        self._exec(
            "INSERT INTO customers(unvan, vergi_no, adres, telefon, eposta, user_id) VALUES (?,?,?,?,?,?)",
            (unvan, vergi_no, adres, telefon, eposta, self.uid),
        )

    def update_customer(self, cid, *, unvan, vergi_no, adres, telefon, eposta):
        self._exec(
            "UPDATE customers SET unvan=?, vergi_no=?, adres=?, telefon=?, eposta=? WHERE id=? AND user_id=?",
            (unvan, vergi_no, adres, telefon, eposta, cid, self.uid),
        )

    def delete_customer(self, cid):
        return self._exec_safe("DELETE FROM customers WHERE id = ? AND user_id = ?", (cid, self.uid))

    # ===================================================================
    #  FATURALAR
    # ===================================================================
    def list_invoices(self, q=None, tip=None):
        conn = self._conn()
        base = """SELECT i.*, c.unvan AS musteri_unvan,
                         COALESCE((SELECT SUM(p.tutar) FROM payments p WHERE p.fatura_id = i.id), 0) AS odenen
                  FROM invoices i LEFT JOIN customers c ON c.id = i.musteri_id"""
        conditions = ["i.user_id = ?"]
        params = [self.uid]
        if tip == "teklif":
            conditions.append("i.fatura_tipi = 'Teklif'")
        elif tip:
            conditions.append("i.fatura_tipi != 'Teklif'")
        if q:
            like = f"%{q}%"
            conditions.append("(i.fatura_no LIKE ? OR c.unvan LIKE ?)")
            params.extend([like, like])
        where = " WHERE " + " AND ".join(conditions)
        rows = conn.execute(base + where + " ORDER BY i.id DESC", params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_invoice(self, iid):
        conn = self._conn()
        row = conn.execute(
            """SELECT i.*, c.unvan AS musteri_unvan, c.vergi_no, c.adres, c.telefon, c.eposta AS musteri_eposta
               FROM invoices i LEFT JOIN customers c ON c.id = i.musteri_id WHERE i.id = ? AND i.user_id = ?""",
            (iid, self.uid),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_invoice(self, data):
        conn = self._conn()
        cur = conn.cursor()
        sql = """INSERT INTO invoices(musteri_id, fatura_no, tarih, urun_kodu, acıklama,
                 "Birim_Fiyat", iskonto, kdv, ara_toplam, iskonto_tutarı, kdv_tutarı,
                 toplam_tutar, fatura_tipi, vade_tarihi, gecerlilik_tarihi, user_id)
               VALUES (:musteri_id, :fatura_no, :tarih, :urun_kodu, :acıklama,
                 :Birim_Fiyat, :iskonto, :kdv, :ara_toplam, :iskonto_tutarı, :kdv_tutarı,
                 :toplam_tutar, :fatura_tipi, :vade_tarihi,
                 :gecerlilik_tarihi, :user_id)"""
        params = {**data, "gecerlilik_tarihi": data.get("gecerlilik_tarihi", ""),
                  "user_id": self.uid}
        new_id = self._insert_returning_id(conn, cur, sql, params)
        conn.close()
        return new_id

    def convert_teklif_to_invoice(self, iid, yeni_no):
        """Teklifin fatura_tipi'ni 'Satış' yapar ve yeni fatura_no atar."""
        self._exec(
            "UPDATE invoices SET fatura_tipi='Satış', fatura_no=? WHERE id=? AND user_id=?",
            (yeni_no, iid, self.uid),
        )

    def delete_invoice(self, iid):
        conn = self._conn()
        # Yalnızca bu kullanıcının faturası ve ona bağlı ödemeler silinir
        conn.execute(
            "DELETE FROM payments WHERE fatura_id = ? AND user_id = ?", (iid, self.uid)
        )
        conn.execute(
            "DELETE FROM invoices WHERE id = ? AND user_id = ?", (iid, self.uid)
        )
        conn.commit()
        conn.close()

    def next_invoice_no(self):
        """FAT2026000001 gibi otomatik fatura no üretir."""
        from datetime import datetime as _dt
        yil = _dt.now().year
        n = self._scalar(
            "SELECT COUNT(*) FROM invoices WHERE user_id = ?", (self.uid,)
        ) + 1
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
               WHERE p.user_id = ?
               ORDER BY p.id DESC""",
            (self.uid,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_payment(self, pid):
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM payments WHERE id = ? AND user_id = ?", (pid, self.uid)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def invoice_options(self):
        """Ödeme formu için faturalar + kalan tutar."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT i.id, i.fatura_no, i.toplam_tutar, c.unvan AS musteri_unvan,
                      COALESCE((SELECT SUM(p.tutar) FROM payments p WHERE p.fatura_id = i.id),0) AS odenen
               FROM invoices i LEFT JOIN customers c ON c.id = i.musteri_id
               WHERE i.user_id = ?
               ORDER BY i.id DESC""",
            (self.uid,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def create_payment(self, *, fatura_id, odeme_tarihi, tutar, odeme_tipi):
        self._exec(
            "INSERT INTO payments(fatura_id, odeme_tarihi, tutar, odeme_tipi, user_id) VALUES (?,?,?,?,?)",
            (fatura_id, odeme_tarihi, tutar, odeme_tipi, self.uid),
        )

    def delete_payment(self, pid):
        self._exec("DELETE FROM payments WHERE id = ? AND user_id = ?", (pid, self.uid))

    # ===================================================================
    #  RAPORLAR (dashboard grafikleri)
    # ===================================================================
    def monthly_revenue(self, months=6):
        """Son N ayın satış cirosu — [{'ay':'2026-06','tutar':1234}, ...]."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT substr(tarih,1,7) AS ay, COALESCE(SUM(toplam_tutar),0) AS tutar
               FROM invoices WHERE user_id = ? AND fatura_tipi='Satış' AND tarih IS NOT NULL
               GROUP BY ay ORDER BY ay DESC LIMIT ?""",
            (self.uid, months),
        ).fetchall()
        conn.close()
        return list(reversed([dict(r) for r in rows]))

    def top_customers(self, limit=5):
        conn = self._conn()
        rows = conn.execute(
            """SELECT c.unvan, COALESCE(SUM(i.toplam_tutar),0) AS toplam
               FROM invoices i JOIN customers c ON c.id = i.musteri_id
               WHERE i.fatura_tipi='Satış' AND i.user_id = ?
               GROUP BY c.id ORDER BY toplam DESC LIMIT ?""",
            (self.uid, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def recent_invoices(self, limit=5):
        conn = self._conn()
        rows = conn.execute(
            """SELECT i.fatura_no, i.tarih, i.toplam_tutar, i.fatura_tipi, c.unvan AS musteri_unvan
               FROM invoices i LEFT JOIN customers c ON c.id = i.musteri_id
               WHERE i.user_id = ?
               ORDER BY i.id DESC LIMIT ?""",
            (self.uid, limit),
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
                "SELECT * FROM expenses WHERE user_id = ? AND (kategori LIKE ? OR aciklama LIKE ?) ORDER BY tarih DESC, id DESC",
                (self.uid, like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE user_id = ? ORDER BY tarih DESC, id DESC", (self.uid,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_expense(self, eid):
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM expenses WHERE id = ? AND user_id = ?", (eid, self.uid)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_expense(self, *, tarih, kategori, aciklama, tutar, odeme_tipi):
        self._exec(
            "INSERT INTO expenses(tarih, kategori, aciklama, tutar, odeme_tipi, olusturulma, user_id) VALUES (?,?,?,?,?,?,?)",
            (tarih, kategori, aciklama, tutar, odeme_tipi,
             datetime.now().isoformat(timespec="seconds"), self.uid),
        )

    def update_expense(self, eid, *, tarih, kategori, aciklama, tutar, odeme_tipi):
        self._exec(
            "UPDATE expenses SET tarih=?, kategori=?, aciklama=?, tutar=?, odeme_tipi=? WHERE id=? AND user_id=?",
            (tarih, kategori, aciklama, tutar, odeme_tipi, eid, self.uid),
        )

    def delete_expense(self, eid):
        self._exec("DELETE FROM expenses WHERE id = ? AND user_id = ?", (eid, self.uid))

    def total_expenses(self):
        return self._scalar(
            "SELECT COALESCE(SUM(tutar),0) FROM expenses WHERE user_id = ?", (self.uid,)
        ) or 0

    # ===================================================================
    #  AYARLAR (anahtar/değer)
    # ===================================================================
    def get_setting(self, anahtar, default=None):
        conn = self._conn()
        row = conn.execute(
            "SELECT deger FROM user_settings WHERE user_id = ? AND anahtar = ?",
            (self.uid, anahtar),
        ).fetchone()
        conn.close()
        return row["deger"] if row else default

    def all_settings(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT anahtar, deger FROM user_settings WHERE user_id = ?", (self.uid,)
        ).fetchall()
        conn.close()
        return {r["anahtar"]: r["deger"] for r in rows}

    def set_setting(self, anahtar, deger):
        self._exec(
            "INSERT INTO user_settings(user_id, anahtar, deger) VALUES (?,?,?) "
            "ON CONFLICT(user_id, anahtar) DO UPDATE SET deger = excluded.deger",
            (self.uid, anahtar, deger),
        )

    # ----- AI yanıt önbelleği (token tasarrufu) ------------------------
    def get_ai_cache(self, key, ttl_saat=6):
        """Önbellekteki cevabı döndürür (TTL içinde değilse None)."""
        key = f"{self.uid}:{key}"          # önbelleği kullanıcıya göre ayır
        conn = self._conn()
        row = conn.execute(
            "SELECT cevap, olusturma FROM ai_cache WHERE soru_hash = ?", (key,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        try:
            olu = datetime.fromisoformat(row["olusturma"])
            if datetime.now() - olu > timedelta(hours=ttl_saat):
                return None
        except (ValueError, TypeError):
            pass
        return row["cevap"]

    def set_ai_cache(self, key, soru, cevap):
        key = f"{self.uid}:{key}"          # önbelleği kullanıcıya göre ayır
        ts = datetime.now().isoformat(timespec="seconds")
        if self.is_pg:
            sql = ("INSERT INTO ai_cache(soru_hash, soru, cevap, olusturma) "
                   "VALUES (?,?,?,?) ON CONFLICT(soru_hash) DO UPDATE SET "
                   "soru=EXCLUDED.soru, cevap=EXCLUDED.cevap, olusturma=EXCLUDED.olusturma")
        else:
            sql = ("INSERT OR REPLACE INTO ai_cache(soru_hash, soru, cevap, olusturma) "
                   "VALUES (?,?,?,?)")
        self._exec(sql, (key, soru, cevap, ts))

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
               WHERE i.fatura_tipi='Satış' AND i.user_id = ?
               ORDER BY i.vade_tarihi ASC""",
            (self.uid,),
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
            "SELECT * FROM products WHERE user_id = ? AND stok <= ? ORDER BY stok ASC",
            (self.uid, threshold),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def customer_statement(self, cid):
        """Müşteri cari ekstresi: faturalar (borç) + ödemeler (alacak), kronolojik."""
        conn = self._conn()
        inv = conn.execute(
            """SELECT id, tarih, fatura_no, fatura_tipi, toplam_tutar
               FROM invoices WHERE musteri_id = ? AND user_id = ?""",
            (cid, self.uid),
        ).fetchall()
        pay = conn.execute(
            """SELECT p.odeme_tarihi AS tarih, p.tutar, p.odeme_tipi, i.fatura_no
               FROM payments p JOIN invoices i ON i.id = p.fatura_id
               WHERE i.musteri_id = ? AND i.user_id = ?""",
            (cid, self.uid),
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

    def _date_where(self, col, start, end):
        # Çok kiracılı izolasyon: tüm rapor sorguları daima user_id ile filtrelenir.
        clauses, params = ["user_id = ?"], [self.uid]
        if start:
            clauses.append(f"{self._date(col)} >= {self._date('?')}")
            params.append(start)
        if end:
            clauses.append(f"{self._date(col)} <= {self._date('?')}")
            params.append(end)
        where = " WHERE " + " AND ".join(clauses)
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
        except Exception as e:
            if _is_integrity_error(e):
                try:
                    conn.rollback()
                except Exception:
                    pass
                return False
            raise
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
                "SELECT * FROM tedarikcilar WHERE user_id = ? AND (unvan LIKE ? OR vergi_no LIKE ? OR eposta LIKE ?) ORDER BY id DESC",
                (self.uid, like, like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tedarikcilar WHERE user_id = ? ORDER BY unvan", (self.uid,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_supplier(self, sid):
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM tedarikcilar WHERE id = ? AND user_id = ?", (sid, self.uid)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_supplier(self, *, unvan, vergi_no, adres, telefon, eposta, notlar):
        self._exec(
            "INSERT INTO tedarikcilar(unvan,vergi_no,adres,telefon,eposta,notlar,olusturulma,user_id) VALUES(?,?,?,?,?,?,?,?)",
            (unvan, vergi_no, adres, telefon, eposta, notlar,
             datetime.now().isoformat(timespec="seconds"), self.uid),
        )

    def update_supplier(self, sid, *, unvan, vergi_no, adres, telefon, eposta, notlar):
        self._exec(
            "UPDATE tedarikcilar SET unvan=?,vergi_no=?,adres=?,telefon=?,eposta=?,notlar=? WHERE id=? AND user_id=?",
            (unvan, vergi_no, adres, telefon, eposta, notlar, sid, self.uid),
        )

    def delete_supplier(self, sid):
        self._exec("DELETE FROM tedarikcilar WHERE id=? AND user_id=?", (sid, self.uid))

    def count_suppliers(self):
        return self._scalar("SELECT COUNT(*) FROM tedarikcilar WHERE user_id = ?", (self.uid,))

    # ===================================================================
    #  KASA / BANKA HESAPLARI
    # ===================================================================
    def list_accounts(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM hesaplar WHERE user_id=? AND aktif=1 ORDER BY tur,ad", (self.uid,)
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["bakiye"] = self.account_balance(d["id"])
            result.append(d)
        return result

    def get_account(self, aid):
        conn = self._conn()
        row = conn.execute("SELECT * FROM hesaplar WHERE id=? AND user_id=?", (aid, self.uid)).fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        d["bakiye"] = self.account_balance(aid)
        return d

    def account_balance(self, aid):
        conn = self._conn()
        row = conn.execute(
            "SELECT bakiye_baslangic FROM hesaplar WHERE id=? AND user_id=?", (aid, self.uid)
        ).fetchone()
        if not row:
            conn.close()
            return 0
        baslangic = row[0] or 0
        hareketler = conn.execute(
            "SELECT COALESCE(SUM(tutar),0) FROM hesap_hareketleri WHERE hesap_id=? AND user_id=?",
            (aid, self.uid),
        ).fetchone()[0] or 0
        conn.close()
        return round(baslangic + hareketler, 2)

    def create_account(self, *, ad, tur, para_birimi, bakiye_baslangic, aciklama):
        self._exec(
            "INSERT INTO hesaplar(ad,tur,para_birimi,bakiye_baslangic,aciklama,user_id) VALUES(?,?,?,?,?,?)",
            (ad, tur, para_birimi, bakiye_baslangic, aciklama, self.uid),
        )

    def update_account(self, aid, *, ad, tur, aciklama):
        self._exec("UPDATE hesaplar SET ad=?,tur=?,aciklama=? WHERE id=? AND user_id=?",
                   (ad, tur, aciklama, aid, self.uid))

    def delete_account(self, aid):
        self._exec("DELETE FROM hesaplar WHERE id=? AND user_id=?", (aid, self.uid))

    def list_account_movements(self, aid):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM hesap_hareketleri WHERE hesap_id=? AND user_id=? ORDER BY tarih DESC,id DESC",
            (aid, self.uid),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_movement(self, *, hesap_id, tarih, aciklama, tutar, tip, referans=""):
        self._exec(
            "INSERT INTO hesap_hareketleri(hesap_id,tarih,aciklama,tutar,tip,referans,olusturulma,user_id) VALUES(?,?,?,?,?,?,?,?)",
            (hesap_id, tarih, aciklama, tutar, tip, referans,
             datetime.now().isoformat(timespec="seconds"), self.uid),
        )

    # ===================================================================
    #  ÇEK / SENET
    # ===================================================================
    def list_checks(self, tur=None, durum=None):
        conn = self._conn()
        clauses, params = ["user_id=?"], [self.uid]
        if tur:
            clauses.append("tur=?"); params.append(tur)
        if durum:
            clauses.append("durum=?"); params.append(durum)
        where = " WHERE " + " AND ".join(clauses)
        rows = conn.execute(
            f"SELECT * FROM cek_senet{where} ORDER BY vade_tarihi ASC", params
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_check(self, cid):
        conn = self._conn()
        row = conn.execute("SELECT * FROM cek_senet WHERE id=? AND user_id=?", (cid, self.uid)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_check(self, *, tur, taraf, tutar, vade_tarihi, durum, notlar):
        self._exec(
            "INSERT INTO cek_senet(tur,taraf,tutar,vade_tarihi,durum,notlar,olusturulma,user_id) VALUES(?,?,?,?,?,?,?,?)",
            (tur, taraf, tutar, vade_tarihi, durum, notlar,
             datetime.now().isoformat(timespec="seconds"), self.uid),
        )

    def update_check(self, cid, *, tur, taraf, tutar, vade_tarihi, durum, notlar):
        self._exec(
            "UPDATE cek_senet SET tur=?,taraf=?,tutar=?,vade_tarihi=?,durum=?,notlar=? WHERE id=? AND user_id=?",
            (tur, taraf, tutar, vade_tarihi, durum, notlar, cid, self.uid),
        )

    def set_check_status(self, cid, durum):
        self._exec("UPDATE cek_senet SET durum=? WHERE id=? AND user_id=?", (durum, cid, self.uid))

    def delete_check(self, cid):
        self._exec("DELETE FROM cek_senet WHERE id=? AND user_id=?", (cid, self.uid))

    # ===================================================================
    #  STOK HAREKETLERİ
    # ===================================================================
    def list_stock_movements(self, pid=None):
        conn = self._conn()
        if pid:
            rows = conn.execute(
                "SELECT s.*, p.name AS urun_adi FROM stok_hareketleri s "
                "JOIN products p ON p.id=s.urun_id WHERE s.urun_id=? AND s.user_id=? ORDER BY s.id DESC",
                (pid, self.uid),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT s.*, p.name AS urun_adi FROM stok_hareketleri s "
                "JOIN products p ON p.id=s.urun_id WHERE s.user_id=? ORDER BY s.id DESC LIMIT 200",
                (self.uid,),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_stock_movement(self, *, urun_id, tur, miktar, aciklama="", referans=""):
        self._exec(
            "INSERT INTO stok_hareketleri(urun_id,tur,miktar,aciklama,referans,olusturulma,user_id) VALUES(?,?,?,?,?,?,?)",
            (urun_id, tur, miktar, aciklama, referans,
             datetime.now().isoformat(timespec="seconds"), self.uid),
        )
        # Stok güncelle (yalnızca kendi ürünü)
        delta = miktar if tur == "Giriş" else -miktar
        self._exec("UPDATE products SET stok = stok + ? WHERE id=? AND user_id=?", (delta, urun_id, self.uid))

    # ===================================================================
    #  BÜTÇE
    # ===================================================================
    def list_budgets(self, yil, ay):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM user_butce WHERE user_id=? AND yil=? AND ay=? ORDER BY kategori",
            (self.uid, yil, ay),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def set_budget(self, yil, ay, kategori, hedef_tutar):
        self._exec(
            "INSERT INTO user_butce(user_id,yil,ay,kategori,hedef_tutar) VALUES(?,?,?,?,?) "
            "ON CONFLICT(user_id,yil,ay,kategori) DO UPDATE SET hedef_tutar=excluded.hedef_tutar",
            (self.uid, yil, ay, kategori, hedef_tutar),
        )

    def budget_actual(self, yil, ay):
        """O ay gerçekleşen giderler — kategori bazlı."""
        ay_str = f"{yil:04d}-{ay:02d}"
        conn = self._conn()
        rows = conn.execute(
            "SELECT kategori, COALESCE(SUM(tutar),0) AS toplam FROM expenses "
            "WHERE user_id=? AND substr(tarih,1,7)=? GROUP BY kategori",
            (self.uid, ay_str),
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
            "SELECT * FROM audit_log WHERE kullanici_id=? ORDER BY id DESC LIMIT ?",
            (self.uid, limit),
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
               LEFT JOIN customers c ON c.id=r.musteri_id
               WHERE r.user_id=? ORDER BY r.id DESC""",
            (self.uid,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def create_recurring(self, *, musteri_id, aciklama, tutar, kdv, periyot, sonraki_tarih):
        self._exec(
            "INSERT INTO tekrarlayan_faturalar(musteri_id,aciklama,tutar,kdv,periyot,sonraki_tarih,aktif,olusturulma,user_id) VALUES(?,?,?,?,?,?,1,?,?)",
            (musteri_id, aciklama, tutar, kdv, periyot, sonraki_tarih,
             datetime.now().isoformat(timespec="seconds"), self.uid),
        )

    def get_recurring(self, rid):
        conn = self._conn()
        row = conn.execute(
            """SELECT r.*, c.unvan AS musteri_unvan FROM tekrarlayan_faturalar r
               LEFT JOIN customers c ON c.id=r.musteri_id WHERE r.id=? AND r.user_id=?""",
            (rid, self.uid),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def update_recurring(self, rid, *, musteri_id, aciklama, tutar, kdv, periyot, sonraki_tarih):
        self._exec(
            """UPDATE tekrarlayan_faturalar
               SET musteri_id=?, aciklama=?, tutar=?, kdv=?, periyot=?, sonraki_tarih=?
               WHERE id=? AND user_id=?""",
            (musteri_id, aciklama, tutar, kdv, periyot, sonraki_tarih, rid, self.uid),
        )

    def toggle_recurring(self, rid):
        conn = self._conn()
        row = conn.execute(
            "SELECT aktif FROM tekrarlayan_faturalar WHERE id=? AND user_id=?", (rid, self.uid)
        ).fetchone()
        conn.close()
        if row:
            self._exec("UPDATE tekrarlayan_faturalar SET aktif=? WHERE id=? AND user_id=?",
                       (0 if row[0] else 1, rid, self.uid))

    def fire_recurring(self, rid):
        """Tekrarlayan faturadan yeni fatura oluşturur ve sonraki tarihi günceller."""
        conn = self._conn()
        r = conn.execute(
            "SELECT r.*, c.unvan AS musteri_unvan FROM tekrarlayan_faturalar r "
            "LEFT JOIN customers c ON c.id=r.musteri_id WHERE r.id=? AND r.user_id=?", (rid, self.uid)
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
        self._exec("UPDATE tekrarlayan_faturalar SET sonraki_tarih=? WHERE id=? AND user_id=?",
                   (dt.isoformat(), rid, self.uid))
        return fatura_no

    def delete_recurring(self, rid):
        self._exec("DELETE FROM tekrarlayan_faturalar WHERE id=? AND user_id=?", (rid, self.uid))

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
               AND i.user_id = ?
               AND vade_tarihi < ? AND vade_tarihi IS NOT NULL
               AND (SELECT COALESCE(SUM(p.tutar),0) FROM payments p WHERE p.fatura_id=i.id) < i.toplam_tutar""",
            (self.uid, bugun)
        ).fetchone()[0]
        if vadesi_gecmis:
            alerts.append({"tip": "danger", "ikon": "⏰",
                           "mesaj": f"{vadesi_gecmis} faturanın vadesi geçmiş",
                           "url": "/raporlar/"})

        # Düşük stok
        dusuk = conn.execute(
            "SELECT COUNT(*) FROM products WHERE user_id = ? AND stok <= 5", (self.uid,)
        ).fetchone()[0]
        if dusuk:
            alerts.append({"tip": "warning", "ikon": "📦",
                           "mesaj": f"{dusuk} ürün düşük stokta (≤5 adet)",
                           "url": "/urunler/"})

        # Bekleyen çekler (7 gün içinde vadeli)
        from datetime import timedelta
        yedi_gun = (date.today() + timedelta(days=7)).isoformat()
        bekleyen_cek = conn.execute(
            "SELECT COUNT(*) FROM cek_senet WHERE user_id=? AND durum='Beklemede' AND vade_tarihi <= ?",
            (self.uid, yedi_gun)
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
               FROM invoices i WHERE fatura_tipi='Satış' AND i.user_id=? AND vade_tarihi IS NOT NULL
               GROUP BY vade_tarihi HAVING kalan > 0""",
            (self.uid,),
        ).fetchall()

        # Son 3 ay ortalama gider
        uc_ay_once = (bugun - timedelta(days=90)).isoformat()
        aylik_gider = conn.execute(
            "SELECT COALESCE(SUM(tutar),0)/3.0 FROM expenses WHERE user_id=? AND tarih >= ?",
            (self.uid, uc_ay_once)
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
                         for r in conn.execute(
                             "SELECT id FROM hesaplar WHERE user_id=? AND aktif=1", (self.uid,)
                         ).fetchall())
        alacaklar = conn.execute(
            """SELECT COALESCE(SUM(i.toplam_tutar),0) -
               COALESCE((SELECT SUM(p.tutar) FROM payments p WHERE p.user_id=?),0) FROM invoices i
               WHERE fatura_tipi='Satış' AND i.user_id=?""",
            (self.uid, self.uid),
        ).fetchone()[0] or 0
        stok_degeri = conn.execute(
            "SELECT COALESCE(SUM(birim_fiyat*stok),0) FROM products WHERE user_id=?", (self.uid,)
        ).fetchone()[0] or 0

        # Yükümlülükler
        borclar = conn.execute(
            """SELECT COALESCE(SUM(toplam_tutar),0) FROM invoices WHERE fatura_tipi='Alış' AND user_id=?""",
            (self.uid,),
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
                "WHERE user_id=? AND fatura_tipi='Satış' AND substr(tarih,1,7)=?",
                (self.uid, ay_str)
            ) or 0

        def ay_gider(ay_str):
            return self._scalar(
                "SELECT COALESCE(SUM(tutar),0) FROM expenses WHERE user_id=? AND substr(tarih,1,7)=?",
                (self.uid, ay_str)
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
                         WHERE ii.musteri_id=c.id AND ii.user_id=?),0) AS odenen,
               COUNT(i.id) AS fatura_sayisi
               FROM customers c
               LEFT JOIN invoices i ON i.musteri_id=c.id AND i.fatura_tipi='Satış' AND i.user_id=?
               WHERE c.user_id=?
               GROUP BY c.id ORDER BY ciro DESC LIMIT ?""",
            (self.uid, self.uid, self.uid, limit),
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
        if self.is_pg:
            sql = ("INSERT INTO bildirim_log(user_id, tip, referans) "
                   "VALUES(?,?,?) ON CONFLICT DO NOTHING")
        else:
            sql = "INSERT OR IGNORE INTO bildirim_log(user_id, tip, referans) VALUES(?,?,?)"
        conn.execute(sql, (user_id, tip, referans))
        conn.commit()
        conn.close()

    # ----- FCM Push Token'ları ------------------------------------------
    def save_fcm_token(self, user_id: int, token: str):
        conn = self._conn()
        now = self._now_sql()
        if self.is_pg:
            sql = (f"INSERT INTO fcm_tokens(user_id, token, olusturulma) "
                   f"VALUES(?, ?, {now}) ON CONFLICT(token) DO UPDATE SET "
                   f"user_id=EXCLUDED.user_id, olusturulma=EXCLUDED.olusturulma")
        else:
            sql = (f"INSERT OR REPLACE INTO fcm_tokens(user_id, token, olusturulma) "
                   f"VALUES(?, ?, {now})")
        conn.execute(sql, (user_id, token))
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
        uid = None
        try:
            from flask import session
            uid = session.get("user_id")
        except Exception:
            uid = None
        g.repo = SqliteRepository(
            current_app.config.get("DATABASE_URL", ""),
            current_app.config["SQLITE_PATH"],
            uid,
        )
    return g.repo
