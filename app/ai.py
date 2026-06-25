"""
Yapay Zekâ Asistanı — OpenRouter (OpenAI uyumlu) üzerinden sohbet.

İşletmenin güncel verilerini (özet) sistem istemine ekleyerek; ciro, gider,
alacak ve stok hakkında soru-cevap yapabilen bir finans danışmanı sağlar.
Anahtar .env içindeki OPENROUTER_API_KEY'den okunur. Pro sürüme özeldir.
"""
import json
import urllib.request
import urllib.error
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, current_app, jsonify)
from .data.repository import get_repo
from .security import pro_required

ai_bp = Blueprint("ai", __name__, url_prefix="/asistan")

MAX_GECMIS = 12  # session'da tutulacak en fazla mesaj çifti


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
        "Sen FinansPro adlı Türk muhasebe yazılımının yapay zekâ asistanısın. "
        "Kullanıcıya kısa, net ve Türkçe yanıt ver. Finans, muhasebe, KDV, nakit "
        "akışı ve tahsilat konularında pratik öneriler sun. Sayısal soruları "
        "aşağıdaki güncel verilere dayanarak yanıtla; veri yoksa varsayım yapma, "
        "eksik olduğunu söyle. Yatırım/hukuki tavsiyede kesin dil kullanma.\n\n"
        + _isletme_ozeti(repo)
    )


def _ai_cagir(messages):
    """OpenRouter sohbet tamamlama çağrısı. (yanıt_metni, hata) döndürür."""
    api_key = current_app.config.get("OPENROUTER_API_KEY")
    if not api_key:
        return None, "AI anahtarı tanımlı değil. web/.env içine OPENROUTER_API_KEY ekleyin."

    url = current_app.config["OPENROUTER_BASE"].rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": current_app.config["AI_MODEL"],
        "messages": messages,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Title", "FinansPro")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"], None
    except urllib.error.HTTPError as e:
        detay = e.read().decode("utf-8", "ignore")[:200]
        return None, f"AI servisi hata verdi ({e.code}). {detay}"
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError) as e:
        return None, f"AI servisine ulaşılamadı: {e}"


@ai_bp.route("/")
@pro_required
def chat():
    gecmis = session.get("ai_chat", [])
    anahtar_var = bool(current_app.config.get("OPENROUTER_API_KEY"))
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
    gecmis.append({"role": "user", "content": soru})

    messages = [{"role": "system", "content": _sistem_istemi(repo)}]
    messages.extend(gecmis[-MAX_GECMIS:])

    cevap, hata = _ai_cagir(messages)
    if hata:
        flash(hata, "danger")
        gecmis.pop()  # başarısız soruyu geçmişten çıkar
    else:
        gecmis.append({"role": "assistant", "content": cevap})

    session["ai_chat"] = gecmis[-(MAX_GECMIS * 2):]
    return redirect(url_for("ai.chat"))


@ai_bp.route("/temizle", methods=["POST"])
@pro_required
def clear():
    session.pop("ai_chat", None)
    flash("Sohbet geçmişi temizlendi.", "info")
    return redirect(url_for("ai.chat"))
