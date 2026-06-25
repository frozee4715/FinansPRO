# Blueprint name: budget_bp
"""Bütçe Takibi modülü — kategori bazlı hedef ve gerçekleşen karşılaştırması."""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .data.repository import get_repo
from .security import login_required

budget_bp = Blueprint("budget", __name__, url_prefix="/butce")

KATEGORILER = ["Personel", "Kira", "Pazarlama", "Teknoloji", "Seyahat", "Diğer"]


@budget_bp.route("/")
@login_required
def index():
    repo = get_repo()
    bugun = date.today()
    try:
        yil = int(request.args.get("yil") or bugun.year)
        ay = int(request.args.get("ay") or bugun.month)
    except (ValueError, TypeError):
        yil, ay = bugun.year, bugun.month

    # O aya ait bütçe hedefleri
    butce_kayitlari = repo.list_budgets(yil, ay)
    hedefler = {b["kategori"]: b["hedef_tutar"] for b in butce_kayitlari}

    # Gerçekleşen tutarlar (expenses tablosundan)
    gerceklesen_map = repo.budget_actual(yil, ay)

    # Kategori bazlı karşılaştırma
    kategoriler_veri = []
    toplam_hedef = 0
    toplam_gerceklesen = 0
    for kat in KATEGORILER:
        hedef = hedefler.get(kat) or 0
        gerceklesen = gerceklesen_map.get(kat) or 0
        if hedef > 0:
            oran = round((gerceklesen / hedef) * 100, 1)
        elif gerceklesen > 0:
            oran = 100.0
        else:
            oran = 0.0
        if oran < 80:
            renk = "yesil"
        elif oran <= 100:
            renk = "sari"
        else:
            renk = "kirmizi"
        kategoriler_veri.append({
            "kategori": kat,
            "hedef": hedef,
            "gerceklesen": gerceklesen,
            "oran": oran,
            "renk": renk,
        })
        toplam_hedef += hedef
        toplam_gerceklesen += gerceklesen

    if toplam_hedef > 0:
        toplam_oran = round((toplam_gerceklesen / toplam_hedef) * 100, 1)
    else:
        toplam_oran = 0.0

    return render_template(
        "budget/index.html",
        kategoriler_veri=kategoriler_veri,
        yil=yil,
        ay=ay,
        toplam_hedef=toplam_hedef,
        toplam_gerceklesen=toplam_gerceklesen,
        toplam_oran=toplam_oran,
        yillar=list(range(bugun.year - 2, bugun.year + 2)),
        aylar=list(range(1, 13)),
    )


@budget_bp.route("/duzenle", methods=["GET", "POST"])
@login_required
def edit():
    repo = get_repo()
    bugun = date.today()
    try:
        yil = int(request.args.get("yil") or request.form.get("yil") or bugun.year)
        ay = int(request.args.get("ay") or request.form.get("ay") or bugun.month)
    except (ValueError, TypeError):
        yil, ay = bugun.year, bugun.month

    if request.method == "POST":
        try:
            yil = int(request.form.get("yil") or bugun.year)
            ay = int(request.form.get("ay") or bugun.month)
        except (ValueError, TypeError):
            yil, ay = bugun.year, bugun.month

        for kat in KATEGORILER:
            try:
                hedef = float(request.form.get(f"hedef_{kat}") or 0)
                if hedef < 0:
                    hedef = 0
            except ValueError:
                hedef = 0
            repo.set_budget(yil, ay, kat, hedef)

        flash(f"{yil}/{ay:02d} bütçe hedefleri kaydedildi. 🎯", "success")
        return redirect(url_for("budget.index", yil=yil, ay=ay))

    # Mevcut hedefleri yükle
    butce_kayitlari = repo.list_budgets(yil, ay)
    hedefler = {b["kategori"]: b["hedef_tutar"] for b in butce_kayitlari}

    return render_template(
        "budget/edit.html",
        kategoriler=KATEGORILER,
        hedefler=hedefler,
        yil=yil,
        ay=ay,
        yillar=list(range(bugun.year - 2, bugun.year + 2)),
        aylar=list(range(1, 13)),
    )
