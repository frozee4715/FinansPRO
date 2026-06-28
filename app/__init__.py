"""
Flask uygulama fabrikası.
"""
from flask import Flask, request

from config import Config
from .data.repository import init_schema, get_repo
from .security import (
    seed_admin, inject_user, inject_pro, generate_csrf_token, validate_csrf,
    hash_password,
)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # İstek gövdesi boyut sınırı — büyük yükleme (DoS) ve devasa görüntü/yedek
    # gönderimlerine karşı. (fatura fotoğrafı tarayıcıda küçültülür; yedek
    # geri yükleme yalnızca admin)
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB

    # Veritabanı şemasını hazırla (idempotent) ve varsayılan admini oluştur
    with app.app_context():
        _backend = "PostgreSQL" if app.config.get("DATABASE_URL") else "SQLite"
        app.logger.warning("Veritabanı motoru: %s", _backend)
        init_schema(app.config)

    # Blueprint'ler
    from .auth.routes import auth_bp
    from .main.routes import main_bp
    from .products import products_bp
    from .customers import customers_bp
    from .invoices import invoices_bp
    from .payments import payments_bp
    from .admin import admin_bp
    from .reports import reports_bp
    from .expenses import expenses_bp
    from .exports import exports_bp
    from .billing import billing_bp
    from .settings import settings_bp
    from .ai import ai_bp
    from .backup import backup_bp
    from .destek import destek_bp
    from .suppliers import suppliers_bp
    from .checks import checks_bp
    from .accounts import accounts_bp
    from .budget import budget_bp
    from .recurring import recurring_bp
    from .notifications import notifications_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(exports_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(destek_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(checks_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(budget_bp)
    app.register_blueprint(recurring_bp)
    app.register_blueprint(notifications_bp)

    # İlk admin kullanıcısını garanti et (uygulama başlarken)
    import os as _os
    with app.app_context():
        seed_admin(app)

        # 1) Demo GİRİŞ hesabını her zaman garanti et — dış dosya import'una
        #    bağımlı DEĞİL, sadece relative import kullanır (her ortamda çalışır).
        #    DEMO_SEED=off ile kapatılabilir.
        if _os.environ.get("DEMO_SEED", "on").lower() != "off":
            try:
                repo = get_repo()
                demo = repo.get_user_by_login("demo@finanspro.com")
                if not demo:
                    uid = repo.create_user(
                        name="Demo Kullanıcı", age=30,
                        eposta="demo@finanspro.com",
                        parola_hash=hash_password("Demo1234"),
                        rol="kullanici",
                    )
                    repo.set_user_plan(uid, "pro")
                    app.logger.warning("Demo giriş hesabı oluşturuldu (demo@finanspro.com).")
            except Exception as _e:
                app.logger.warning("Demo hesabı oluşturulamadı: %s", _e)

            # 2) Zengin demo verisi (müşteri/fatura/...): DB boşsa kur — en iyi çaba.
            try:
                from seed_demo import seed_if_empty
                if seed_if_empty():
                    app.logger.warning("Demo verisi otomatik kuruldu (DB boştu).")
            except Exception as _e:
                app.logger.warning("Demo veri tohumlama atlandı: %s", _e)

    # CSRF: her POST/PUT/DELETE'yi doğrula; token'ı tüm şablonlara enjekte et
    app.before_request(validate_csrf)
    app.jinja_env.globals["csrf_token"] = generate_csrf_token

    # Güvenlik HTTP başlıkları — her yanıta eklenir
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # HSTS: HTTPS kullanıyorsan tarayıcı bir daha HTTP'ye gitmesin (1 yıl)
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # CSP: kendi kaynaklarımız + izin verilen CDN'ler
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
                "https://www.gstatic.com https://apis.google.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://cdn.jsdelivr.net https://twemoji.maxcdn.com; "
            "connect-src 'self' https://*.googleapis.com https://*.firebaseio.com "
                "https://www.gstatic.com https://cdn.jsdelivr.net; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        return response

    # Her şablona giriş yapan kullanıcıyı ve Pro durumunu enjekte et
    app.context_processor(inject_user)
    app.context_processor(inject_pro)

    # Marka + işletme ayarları tüm şablonlarda kullanılabilsin
    @app.context_processor
    def inject_brand():
        try:
            repo = get_repo()
            ayar = repo.all_settings()        # tek sorgu (7 ayrı sorgu yerine)
            para          = ayar.get("para_birimi")     or app.config["DEFAULT_CURRENCY"]
            renk          = ayar.get("marka_renk")      or ""
            ikincil       = ayar.get("ikincil_renk")    or ""
            yazi_tipi     = ayar.get("yazi_tipi")       or ""
            kose_yuvarlak = ayar.get("kose_yuvarlak")   or ""
            kompakt_mod   = ayar.get("kompakt_mod")     or ""
            sidebar_gen   = ayar.get("sidebar_genislik") or ""
        except Exception:
            para, renk, ikincil, yazi_tipi, kose_yuvarlak, kompakt_mod, sidebar_gen = (
                app.config["DEFAULT_CURRENCY"], "", "", "", "", "", ""
            )
        return {
            "APP_NAME":        app.config["APP_NAME"],
            "APP_TAGLINE":     app.config["APP_TAGLINE"],
            "CURRENCY":        para,
            "MARKA_RENK":      renk,
            "IKINCIL_RENK":    ikincil,
            "YAZI_TIPI":       yazi_tipi,
            "KOSE_YUVARLAK":   kose_yuvarlak,
            "KOMPAKT_MOD":     kompakt_mod,
            "SIDEBAR_GENISLIK": sidebar_gen,
            # FCM push bildirimleri (boşsa şablonda gizlenir)
            "FCM_API_KEY":             app.config.get("FCM_API_KEY", ""),
            "FCM_AUTH_DOMAIN":         app.config.get("FCM_AUTH_DOMAIN", ""),
            "FCM_PROJECT_ID":          app.config.get("FCM_PROJECT_ID", ""),
            "FCM_STORAGE_BUCKET":      app.config.get("FCM_STORAGE_BUCKET", ""),
            "FCM_MESSAGING_SENDER_ID": app.config.get("FCM_MESSAGING_SENDER_ID", ""),
            "FCM_APP_ID":              app.config.get("FCM_APP_ID", ""),
            "FCM_VAPID_KEY":           app.config.get("FCM_VAPID_KEY", ""),
        }

    # Henüz oluşturulmamış rotalara güvenli bağlantı (sonraki aşamalar için)
    from flask import url_for
    from werkzeug.routing import BuildError

    @app.template_global()
    def safe_url(endpoint, **values):
        try:
            return url_for(endpoint, **values)
        except BuildError:
            return "#"

    return app
