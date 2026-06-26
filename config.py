"""
Uygulama yapılandırması.
Tüm ortam ayarları burada toplanır; böylece Firebase'e geçişte
yalnızca bu dosya ve veri katmanı (app/data) değişir.
"""
import os
import secrets
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()                       # web/.env dosyasını yükler (varsa)
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent


class Config:
    # Güvenlik — ÜRETİMDE mutlaka ortam değişkeni (SECRET_KEY) ile verin.
    # Sabit/tahmin edilebilir bir varsayılan KULLANILMAZ: env yoksa her
    # başlatmada rastgele üretilir (çok işçili üretimde env ŞART, aksi halde
    # oturumlar işçiler arasında doğrulanmaz — bu da yanlış kurulumu görünür kılar).
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    # Cookie güvenliği
    SESSION_COOKIE_HTTPONLY = True          # JS'nin cookie'ye erişimini engeller
    SESSION_COOKIE_SAMESITE = "Lax"        # CSRF'e karşı temel koruma
    # Üretimde HTTPS zorunluysa True yapın (geliştirme ortamında False bırakın)
    SESSION_COOKIE_SECURE = os.environ.get("HTTPS_ENABLED", "false").lower() == "true"

    # Veri kaynağı: "sqlite" (şimdilik) | "firebase" (geçiş sonrası)
    DATA_BACKEND = os.environ.get("DATA_BACKEND", "sqlite")

    # SQLite — mevcut emuhasebe.db dosyasını kullanır (proje kökünde)
    SQLITE_PATH = os.environ.get("SQLITE_PATH", str(PROJECT_ROOT / "emuhasebe.db"))

    # Firebase Admin SDK (sunucu tarafı bildirim gönderimi)
    # Firebase Console → Proje Ayarları → Hizmet Hesapları → Yeni özel anahtar oluştur
    FIREBASE_CREDENTIALS = os.environ.get("FIREBASE_CREDENTIALS", "")
    FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "")

    # Firebase Web App yapılandırması (FCM push bildirimleri)
    # Firebase Console → Proje Ayarları → Genel → Web uygulaması yapılandırması
    FCM_API_KEY             = os.environ.get("FCM_API_KEY", "")
    FCM_AUTH_DOMAIN         = os.environ.get("FCM_AUTH_DOMAIN", "")
    FCM_PROJECT_ID          = os.environ.get("FCM_PROJECT_ID", "")
    FCM_STORAGE_BUCKET      = os.environ.get("FCM_STORAGE_BUCKET", "")
    FCM_MESSAGING_SENDER_ID = os.environ.get("FCM_MESSAGING_SENDER_ID", "")
    FCM_APP_ID              = os.environ.get("FCM_APP_ID", "")
    # Firebase Console → Proje Ayarları → Cloud Messaging → Web Push sertifikaları → Anahtar çifti
    FCM_VAPID_KEY           = os.environ.get("FCM_VAPID_KEY", "")

    # Oturum süresi
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8 saat

    # Giriş güvenliği
    MAX_LOGIN_ATTEMPTS = 3
    LOCKOUT_MINUTES = 5

    # Uygulama markası
    APP_NAME = "FinansPro"
    APP_TAGLINE = "Akıllı e-Muhasebe Çözümü"

    # Varsayılan işletme & muhasebe ayarları (Ayarlar sayfasından değiştirilir)
    DEFAULT_CURRENCY = "₺"
    DEFAULT_KDV = "20"

    # Yapay zekâ (OpenRouter) — anahtar ortam değişkeninden / .env'den okunur
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
    AI_MODEL = os.environ.get("AI_MODEL", "poolside/laguna-xs.2:free")
    # Fatura fotoğrafı okuma için görüntü destekli (vision) model
    AI_VISION_MODEL = os.environ.get(
        "AI_VISION_MODEL", "meta-llama/llama-3.2-11b-vision-instruct:free"
    )

    # E-posta (SMTP) — .env'de tanımlayın
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = os.environ.get("SMTP_PORT", "587")
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASS = os.environ.get("SMTP_PASS", "")
