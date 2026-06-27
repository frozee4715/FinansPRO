"""
Yapay Zekâ Asistanı — OpenRouter (OpenAI uyumlu) üzerinden sohbet.

İşletmenin güncel verilerini (özet) sistem istemine ekleyerek; ciro, gider,
alacak ve stok hakkında soru-cevap yapabilen bir finans danışmanı sağlar.
Anahtar .env içindeki OPENROUTER_API_KEY'den okunur. Pro sürüme özeldir.
"""
import json
import re
import hashlib
import urllib.request
import urllib.error
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, current_app, jsonify)
from .data.repository import get_repo
from .security import pro_required

ai_bp = Blueprint("ai", __name__, url_prefix="/asistan")

MAX_GECMIS = 12  # session'da tutulacak en fazla mesaj çifti


def _normalize_soru(s):
    """Soruyu önbellek anahtarı için normalize eder (küçük harf, boşluk, noktalama)."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ?!.,;:\n\t")


def _veri_parmak_izi(repo):
    """İşletme verisinin kısa parmak izi — veri değişince önbellek tazelensin."""
    try:
        st = repo.dashboard_stats()
        ie = repo.income_expense()
        return (f"{st.get('musteri')}-{st.get('urun')}-{st.get('fatura')}-"
                f"{round(ie.get('gelir', 0))}-{round(ie.get('gider', 0))}")
    except Exception:
        return "x"


def _cache_key(soru, fp):
    return hashlib.sha256((_normalize_soru(soru) + "|" + fp).encode("utf-8")).hexdigest()


def _isletme_ozeti(repo):
    """Modelin bağlam olarak kullanacağı kısa işletme özeti (Türkçe)."""
    s = repo.dashboard_stats()
    ie = repo.income_expense()
    kdv = repo.kdv_summary()
    aging = repo.receivables_aging()
    dusuk = repo.low_stock_products(5)
    acik = sum(r["kalan"] for r in aging)
    gecikmis = sum(r["kalan"] for r in aging if (r["gecikme_gun"] or 0) > 0)
    satir = [
        "GÜNCEL İŞLETME VERİLERİ (₺):",
        f"- Toplam ciro (satış): {ie['gelir']:.2f}",
        f"- Toplam alış: {ie['alis']:.2f}",
        f"- Toplam gider: {ie['gider']:.2f}",
        f"- Tahmini kâr: {ie['kar']:.2f}",
        f"- Hesaplanan KDV: {kdv['hesaplanan']:.2f}, İndirilecek KDV: {kdv['indirilecek']:.2f}, Ödenecek KDV: {kdv['odenecek']:.2f}",
        f"- Açık (tahsil edilmemiş) alacak: {acik:.2f}, bunun vadesi geçen: {gecikmis:.2f}",
        f"- Müşteri: {s['musteri']}, Ürün: {s['urun']}, Fatura: {s['fatura']}",
        f"- Düşük stoklu ürün sayısı (≤5): {len(dusuk)}",
    ]
    if dusuk:
        adlar = ", ".join(f"{p['name']} ({p['stok']})" for p in dusuk[:8])
        satir.append(f"- Düşük stoklular: {adlar}")
    return "\n".join(satir)


def _sistem_istemi(repo):
    return (
        "Sen MuhasebePRO adlı Türk muhasebe yazılımının yapay zekâ asistanısın. "
        "Kullanıcıya kısa, net ve Türkçe yanıt ver. Finans, muhasebe, KDV, nakit "
        "akışı ve tahsilat konularında pratik öneriler sun. Sayısal soruları "
        "aşağıdaki güncel verilere dayanarak yanıtla; veri yoksa varsayım yapma, "
        "eksik olduğunu söyle. Yatırım/hukuki tavsiyede kesin dil kullanma.\n\n"
        + _isletme_ozeti(repo)
    )


def _or_keys():
    """Sırasıyla denenecek OpenRouter anahtarları: önce birincil, sonra yedek."""
    keys = []
    for ad in ("OPENROUTER_API_KEY", "OPENROUTER_API_KEY_BACKUP"):
        k = current_app.config.get(ad)
        if k:
            keys.append(k)
    return keys


def _or_post(payload_dict, timeout):
    """OpenRouter'a POST eder; birincil anahtar limit/kota verince yedeğe geçer.
    (yanıt_json, hata) döndürür."""
    keys = _or_keys()
    if not keys:
        return None, ("AI anahtarı tanımlı değil. Ortam değişkenlerine "
                      "OPENROUTER_API_KEY ekleyin.")
    url = current_app.config["OPENROUTER_BASE"].rstrip("/") + "/chat/completions"
    body = json.dumps(payload_dict).encode("utf-8")
    son_hata = None
    for i, key in enumerate(keys):
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Title", "MuhasebePRO")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            detay = e.read().decode("utf-8", "ignore")[:200]
            son_hata = f"AI servisi hata verdi ({e.code}). {detay}"
            # 401/402 (yetki/kota) veya 429 (limit) → varsa yedek anahtarı dene
            if e.code in (401, 402, 429) and i < len(keys) - 1:
                continue
            return None, son_hata
        except (urllib.error.URLError, ValueError, TimeoutError) as e:
            son_hata = f"AI servisine ulaşılamadı: {e}"
            if i < len(keys) - 1:    # ağ hatasında da yedeği dene
                continue
            return None, son_hata
    return None, son_hata


def _ai_cagir(messages):
    """OpenRouter sohbet tamamlama çağrısı. (yanıt_metni, hata) döndürür."""
    data, hata = _or_post({
        "model": current_app.config["AI_MODEL"],
        "messages": messages,
        "max_tokens": current_app.config.get("AI_MAX_TOKENS", 600),
        "reasoning": {"enabled": True},
    }, timeout=60)
    if hata:
        return None, hata
    try:
        return data["choices"][0]["message"]["content"], None
    except (KeyError, IndexError, TypeError):
        return None, "AI yanıtı çözümlenemedi."


def _json_ayikla(metin):
    """Model yanıtından JSON nesnesini ayıklar (```json çitlerini temizler)."""
    if not metin:
        return None
    t = metin.strip()
    if t.startswith("```"):
        # ```json ... ``` veya ``` ... ```
        t = t.split("```", 2)
        t = t[1] if len(t) > 1 else metin
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    # İlk { ve son } arasını al
    bas = t.find("{")
    son = t.rfind("}")
    if bas == -1 or son == -1 or son < bas:
        return None
    try:
        return json.loads(t[bas:son + 1])
    except (ValueError, TypeError):
        return None


def vision_json(image_data_url, instruction):
    """Görüntüyü (data URL) görüntü destekli modele gönderip JSON çıkarır.
    (dict, hata_metni) döndürür."""
    if not _or_keys():
        return None, ("AI anahtarı tanımlı değil. Bu özellik için ortam "
                      "değişkenlerine OPENROUTER_API_KEY ekleyin.")

    model = (current_app.config.get("AI_VISION_MODEL")
             or current_app.config["AI_MODEL"])
    data, hata = _or_post({
        "model": model,
        "temperature": 0,
        "max_tokens": 700,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }],
    }, timeout=90)
    if hata:
        return None, hata
    try:
        icerik = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None, "AI yanıtı çözümlenemedi."

    parsed = _json_ayikla(icerik)
    if parsed is None:
        return None, "Fatura okunamadı. Daha net/düz bir fotoğraf deneyin."
    return parsed, None


@ai_bp.route("/")
@pro_required
def chat():
    gecmis = session.get("ai_chat", [])
    anahtar_var = bool(_or_keys())
    return render_template("ai/chat.html", gecmis=gecmis,
                           anahtar_var=anahtar_var,
                           model=current_app.config["AI_MODEL"])


@ai_bp.route("/gonder", methods=["POST"])
@pro_required
def send():
    soru = (request.form.get("mesaj") or "").strip()
    if not soru:
        return redirect(url_for("ai.chat"))

    repo = get_repo()
    gecmis = session.get("ai_chat", [])

    # Standalone (ilk) soru mu? Sadece bunları önbellekten ver/önbelleğe al;
    # sohbet takip soruları bağlama bağlı olduğu için her zaman API'ye gider.
    standalone = not any(m["role"] == "assistant" for m in gecmis)
    gecmis.append({"role": "user", "content": soru})

    # --- Önbellek kontrolü (token harcamadan) ---
    if standalone:
        key = _cache_key(soru, _veri_parmak_izi(repo))
        ttl = current_app.config.get("AI_CACHE_TTL_HOURS", 6)
        onbellek = repo.get_ai_cache(key, ttl)
        if onbellek:
            gecmis.append({"role": "assistant", "content": onbellek})
            session["ai_chat"] = gecmis[-(MAX_GECMIS * 2):]
            return redirect(url_for("ai.chat"))

    messages = [{"role": "system", "content": _sistem_istemi(repo)}]
    messages.extend(gecmis[-MAX_GECMIS:])

    cevap, hata = _ai_cagir(messages)
    if hata:
        flash(hata, "danger")
        gecmis.pop()  # başarısız soruyu geçmişten çıkar
    else:
        gecmis.append({"role": "assistant", "content": cevap})
        if standalone:
            repo.set_ai_cache(_cache_key(soru, _veri_parmak_izi(repo)), soru, cevap)

    session["ai_chat"] = gecmis[-(MAX_GECMIS * 2):]
    return redirect(url_for("ai.chat"))


@ai_bp.route("/temizle", methods=["POST"])
@pro_required
def clear():
    session.pop("ai_chat", None)
    flash("Sohbet geçmişi temizlendi.", "info")
    return redirect(url_for("ai.chat"))
