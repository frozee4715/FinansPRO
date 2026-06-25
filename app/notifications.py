"""Push bildirimleri blueprint'i."""
import traceback
from flask import Blueprint, request, jsonify, session, current_app, render_template

from .data.repository import get_repo
from .security import login_required

notifications_bp = Blueprint("notifications", __name__, url_prefix="/bildirimler")


@notifications_bp.route("/firebase-messaging-sw.js")
def fcm_sw():
    """FCM service worker'ını kök path'ten servis eder (FCM zorunluluğu)."""
    resp = current_app.make_response(
        render_template("partials/firebase_sw.html")
    )
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@notifications_bp.route("/token", methods=["POST"])
@login_required
def register_token():
    """Tarayıcı FCM token'ını kaydeder."""
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "hata": "Token boş"}), 400

    user_id = session["user_id"]
    get_repo().save_fcm_token(user_id, token)
    return jsonify({"ok": True})


@notifications_bp.route("/token", methods=["DELETE"])
@login_required
def delete_token():
    """FCM token'ını siler (bildirimlerden çıkma)."""
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if token:
        get_repo().delete_fcm_token(token)
    return jsonify({"ok": True})


@notifications_bp.route("/test", methods=["POST"])
@login_required
def test_notification():
    """Mevcut kullanıcıya test bildirimi gönderir."""
    from .firebase_utils import _get_firebase_app, send_push

    user_id = session["user_id"]
    tokens = get_repo().get_user_fcm_tokens(user_id)
    if not tokens:
        return jsonify({"ok": False, "hata": "Token bulunamadi. Sayfayi yenile ve bildirime izin ver."}), 400

    try:
        app = _get_firebase_app()
    except Exception as exc:
        return jsonify({"ok": False, "hata": "Firebase init hatasi: " + str(exc)}), 500

    if app is None:
        return jsonify({"ok": False, "hata": "Firebase baslatılamadi. Credentials dosyasi ve .env kontrol et."}), 500

    basarili = 0
    son_hata = ""
    for token in tokens:
        try:
            ok = send_push(token, "FinansPro Test", "Push bildirimleri calisiyor!", "/panel")
            if ok:
                basarili += 1
        except Exception as exc:
            son_hata = traceback.format_exc()[-300:]

    if basarili == 0:
        return jsonify({"ok": False, "hata": son_hata or "Gonderim basarisiz"}), 500
    return jsonify({"ok": True, "gonderilen": basarili})
