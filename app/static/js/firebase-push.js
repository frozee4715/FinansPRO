/* Firebase Cloud Messaging — tarayıcı tarafı */
(function () {
    'use strict';

    if (!window.FCM_CONFIG || !window.FCM_CONFIG.apiKey) return;
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;

    if (!firebase.apps.length) {
        firebase.initializeApp(window.FCM_CONFIG);
    }

    const messaging = firebase.messaging();

    // Ön planda gelen bildirimleri göster
    messaging.onMessage(function (payload) {
        const n = payload.notification || {};
        if (Notification.permission === 'granted') {
            new Notification(n.title || 'FinansPro', {
                body: n.body || '',
                icon: '/static/img/logo-mark.svg'
            });
        }
    });

    function getCsrf() {
        var m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    }

    function registerToken(token) {
        fetch('/bildirimler/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
            body: JSON.stringify({ token: token })
        }).catch(function (err) { console.warn('[FCM] Token kaydedilemedi:', err); });
    }

    // SW'yi kaydet → token al
    navigator.serviceWorker.register('/bildirimler/firebase-messaging-sw.js', { scope: '/' })
        .then(function (reg) {
            return Notification.requestPermission().then(function (permission) {
                if (permission !== 'granted') {
                    console.log('[FCM] Bildirim izni reddedildi.');
                    return;
                }
                // v10 compat: serviceWorkerRegistration doğrudan getToken'a geçirilir
                return messaging.getToken({
                    vapidKey: window.FCM_VAPID_KEY,
                    serviceWorkerRegistration: reg
                }).then(function (token) {
                    if (token) {
                        window._fcmToken = token;
                        registerToken(token);
                        console.log('[FCM] Token alındı ve kaydedildi.');
                    }
                });
            });
        })
        .catch(function (err) { console.warn('[FCM] Hata:', err); });

}());
