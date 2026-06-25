"""Firebase Cloud Messaging — sunucu tarafı gönderici.

Kullanım:
    from .firebase_utils import send_push, send_push_to_user
    send_push_to_user(user_id=1, title="Bildirim", body="Mesaj", url="/panel")

Kurulum:
    1. Firebase Console → Proje Ayarları → Hizmet Hesapları → Yeni özel anahtar oluştur
    2. İndirilen JSON dosyasını projede güvenli bir yere koy (örn. web/firebase-creds.json)
    3. .env dosyasına ekle: FIREBASE_CREDENTIALS=web/firebase-creds.json
"""
import json
import logging
from flask import current_app

logger = logging.getLogger(__name__)

_firebase_app = None


def _get_firebase_app():
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    try:
        import firebase_admin
        from firebase_admin import credentials

        # 1. Önce FIREBASE_CREDENTIALS_JSON ortam değişkenini dene (Railway/cloud)
        import os
        creds_json = os.environ.get("FIREBASE_CREDENTIALS_JSON", "")
        if creds_json:
            cred_dict = json.loads(creds_json)
            cred = credentials.Certificate(cred_dict)
        else:
            # 2. Yoksa dosya yolunu dene (lokal geliştirme)
            creds_path = current_app.config.get("FIREBASE_CREDENTIALS", "")
            if not creds_path:
                return None
            from pathlib import Path
            p = Path(creds_path)
            if not p.is_absolute():
                p = Path(current_app.root_path).parent / creds_path
            if not p.exists():
                logger.warning("Firebase credentials dosyası bulunamadı: %s", p)
                return None
            cred = credentials.Certificate(str(p))

        if not firebase_admin._apps:
            _firebase_app = firebase_admin.initialize_app(cred)
        else:
            _firebase_app = firebase_admin.get_app()
        return _firebase_app
    except Exception as exc:
        import traceback
        traceback.print_exc()
        logger.warning("Firebase Admin SDK başlatılamadı: %s", exc)
        return None


def send_push(token: str, title: str, body: str, url: str = "/panel") -> bool:
    """Tek bir FCM token'a bildirim gönderir. Başarı durumunda True döner."""
    app = _get_firebase_app()
    if app is None:
        raise RuntimeError("Firebase app başlatılamadı — credentials kontrolü yapın.")

    from firebase_admin import messaging

    webpush_cfg = messaging.WebpushConfig(
        notification=messaging.WebpushNotification(
            title=title,
            body=body,
            icon="/static/img/logo-mark.svg",
        ),
    )
    # FCM link yalnızca tam HTTPS URL'de çalışır
    if url and url.startswith("https://"):
        webpush_cfg.fcm_options = messaging.WebpushFCMOptions(link=url)

    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        webpush=webpush_cfg,
        token=token,
    )
    messaging.send(message)
    return True


def send_push_to_user(user_id: int, title: str, body: str, url: str = "/panel") -> int:
    """Kullanıcının kayıtlı tüm cihazlarına bildirim gönderir. Başarılı gönderim sayısını döner."""
    from .data.repository import get_repo

    tokens = get_repo().get_user_fcm_tokens(user_id)
    count = 0
    for token in tokens:
        if send_push(token, title, body, url):
            count += 1
    return count


def notify_user_event(user_id: int, tip: str, referans: str, title: str, body: str, url: str = "/panel"):
    """Tekrar göndermeden bir kullanıcıya olay bildirimi gönderir."""
    from .data.repository import get_repo
    repo = get_repo()
    if repo.bildirim_gonderildi_mi(user_id, tip, referans):
        return
    if send_push_to_user(user_id, title, body, url) > 0:
        repo.bildirim_logla(user_id, tip, referans)


def check_and_notify(user_id: int):
    """Dashboard yüklendiğinde vadesi geçmiş fatura ve düşük stok bildirimlerini kontrol eder."""
    from datetime import date
    from .data.repository import get_repo
    repo = get_repo()

    bugun = date.today().isoformat()

    # Vadesi gelen / geçmiş faturalar
    try:
        aging = repo.receivables_aging()
        for r in aging:
            gecikme = r.get("gecikme_gun")
            if gecikme is None or r.get("kalan", 0) <= 0:
                continue
            fatura_id = str(r.get("fatura_id") or r.get("id") or "")
            if not fatura_id:
                continue

            if gecikme == 0:
                # Bugün vadesi geliyor
                notify_user_event(
                    user_id,
                    tip="vade_bugun",
                    referans=fatura_id,
                    title="Bugün Vadesi Geliyor",
                    body=f"{r.get('musteri_unvan', r.get('musteri', 'Müşteri'))} — {r.get('kalan', 0):,.0f}₺ bugün vadeli",
                    url="/faturalar",
                )
            elif gecikme > 0:
                # Vadesi geçmiş
                notify_user_event(
                    user_id,
                    tip="vade_gecmis",
                    referans=fatura_id,
                    title="Vadesi Geçmiş Fatura",
                    body=f"{r.get('musteri_unvan', r.get('musteri', 'Müşteri'))} — {r.get('kalan', 0):,.0f}₺, {gecikme} gün gecikmiş",
                    url="/faturalar",
                )
            elif -3 <= gecikme < 0:
                # 1-3 gün sonra vadesi geliyor (erken uyarı, fatura başına tek sefer)
                gun_kalan = abs(gecikme)
                notify_user_event(
                    user_id,
                    tip="vade_yaklasıyor",
                    referans=fatura_id,
                    title="Yaklaşan Vade",
                    body=f"{r.get('musteri_unvan', r.get('musteri', 'Müşteri'))} — {r.get('kalan', 0):,.0f}₺, {gun_kalan} gün sonra vadeli",
                    url="/faturalar",
                )
    except Exception:
        pass

    # Düşük stok
    try:
        dusuk = repo.low_stock_products(10)
        for p in dusuk:
            if (p.get("stok") or 0) <= 0:
                notify_user_event(
                    user_id,
                    tip="stok_tukendi",
                    referans=str(p.get("id", "")),
                    title="Stok Tükendi",
                    body=f"{p.get('name', 'Ürün')} stoğu bitti!",
                    url="/urunler",
                )
            elif (p.get("stok") or 0) <= 5:
                referans = f"dusuk_{p.get('id', '')}_{bugun}"
                notify_user_event(
                    user_id,
                    tip="dusuk_stok",
                    referans=referans,
                    title="Düşük Stok Uyarısı",
                    body=f"{p.get('name', 'Ürün')} — sadece {p.get('stok', 0)} adet kaldı",
                    url="/urunler",
                )
    except Exception:
        pass


def notify_payment_received(user_id: int, musteri: str, tutar: float, fatura_id: int):
    """Ödeme alındığında bildirim gönderir."""
    notify_user_event(
        user_id,
        tip="odeme_alindi",
        referans=str(fatura_id),
        title="Ödeme Alındı",
        body=f"{musteri} — {tutar:,.0f}₺ ödeme geldi",
        url="/odemeler",
    )


def send_push_broadcast(title: str, body: str, url: str = "/panel") -> int:
    """Tüm kayıtlı token'lara toplu bildirim gönderir."""
    from .data.repository import get_repo

    all_tokens = get_repo().get_all_fcm_tokens()
    count = 0
    for row in all_tokens:
        if send_push(row["token"], title, body, url):
            count += 1
    return count
