import re
import sqlite3
import calendar
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from datetime import date, timedelta
from pathlib import Path
from openpyxl import Workbook
from openpyxl.drawing.image import Image
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "biscuiterie.db"
SQL = [BASE / "sql" / "ecarts.sql", BASE / "sql" / "rentabilite.sql"]
OUT = BASE / "resultats"
GRAPH = OUT / "graphiques"
ANNEE = 2026
SEUIL = 25_000
MOIS = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MOIS_L = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

BLEU, ORANGE, VERT_EAU, ROUGE, GRIS, ENCRE, ENCRE2, GRILLE = "#2a78d6", "#eb6834", "#1baf7a", "#e34948", "#9a9993", "#0b0b0b", "#52514e", "#e6e5e1"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRIS, "axes.labelcolor": ENCRE2,
                     "xtick.color": ENCRE2, "ytick.color": ENCRE2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRILLE, "grid.linewidth": 0.8,
                     "axes.titleweight": "bold", "axes.titlesize": 12, "axes.titlelocation": "left", "figure.dpi": 150})
k_eur = FuncFormatter(lambda x, _: f"{x / 1000:,.0f} k€".replace(",", " "))
eur = lambda x: f"{x:,.0f}".replace(",", " ")
keur = lambda x: f"{x / 1000:+,.0f} k€".replace(",", " ")
pfr = lambda x, signe=True: (f"{x:+.1%}" if signe else f"{x:.1%}").replace(".", ",").replace("%", " %")
num = lambda x: f"{x:.1f}".replace(".", ",")
num2 = lambda x: f"{x:.2f}".replace(".", ",")
minus = lambda s: s[0].lower() + s[1:]

if not DB.exists():
    raise SystemExit("Base introuvable : lance d'abord generer_donnees.py")

with sqlite3.connect(DB) as cx:
    if not cx.execute("SELECT 1 FROM sqlite_master WHERE name = 'previsions'").fetchone():
        raise SystemExit("Table previsions introuvable : lance d'abord rolling_forecast.py")
    for f in SQL:
        cx.executescript(f.read_text(encoding="utf-8"))
    q = lambda s: pd.read_sql(s, cx, params={"a": ANNEE})
    pont_m = q("SELECT * FROM v_pont_mensuel WHERE annee = :a")
    ev = q("SELECT * FROM v_ecarts_ventes WHERE annee = :a")
    em = q("SELECT * FROM v_ecarts_matieres WHERE annee = :a")
    emo = q("SELECT * FROM v_ecarts_mo WHERE annee = :a")
    ef = q("SELECT * FROM v_ecarts_fixes WHERE annee = :a")
    ed = q("SELECT * FROM v_ecarts_distribution WHERE annee = :a")
    rent = q("SELECT * FROM v_rentabilite")
    fx = q("SELECT * FROM v_charges_fixes")
    prev = q("SELECT * FROM previsions")
    prev_f = q("SELECT * FROM previsions_charges_fixes")
    bt = q("SELECT * FROM backtest_modeles")
    LIB = {t: dict(cx.execute(f"SELECT code, libelle FROM {t}").fetchall()) for t in ("produits", "canaux", "matieres", "natures_fixes", "gammes")}

dernier = int(ev["mois"].max())
h = 12 - dernier
OUT.mkdir(exist_ok=True)
GRAPH.mkdir(exist_ok=True)
fichier = OUT / f"reporting_{ANNEE}-{dernier:02d}.xlsx"
date_arrete = date(ANNEE, dernier, calendar.monthrange(ANNEE, dernier)[1])

pont = pont_m.groupby(["ordre", "poste"], as_index=False)["montant"].sum()
res_b_cum, res_r_cum = pont["montant"].iloc[0], pont["montant"].iloc[-1]

v_prod = ev.groupby("produit").agg(ca_b=("ca_b", "sum"), ca_r=("ca_r", "sum"), prix=("ecart_prix", "sum"),
                                   volume=("ecart_volume", "sum"), mix=("ecart_mix", "sum"), vol_b=("vol_b", "sum"), vol_r=("vol_r", "sum"))
v_can = ev.groupby("canal").agg(vol_b=("vol_b", "sum"), vol_r=("vol_r", "sum"), prix=("ecart_prix", "sum"),
                                volume=("ecart_volume", "sum"), mix=("ecart_mix", "sum"))
mat = em.groupby("matiere").agg(cout_std=("cout_std", "sum"), cout_r=("cout_r", "sum"), prix=("ecart_prix", "sum"),
                                quantite=("ecart_quantite", "sum"), qte_r=("qte_r", "sum"), prix_std=("prix_std", "mean"))
mat["hausse"] = mat["cout_r"] / mat["qte_r"] / mat["prix_std"] - 1
mo = emo.groupby("produit").agg(h_std=("heures_std", "sum"), h_r=("heures_r", "sum"), cout_std=("cout_std", "sum"),
                                cout_r=("cout_r", "sum"), taux=("ecart_taux", "sum"), rendement=("ecart_rendement", "sum"))
fix = ef.groupby("nature").agg(budget=("montant_b", "sum"), reel=("montant_r", "sum"))

familles = {1: "Prix de vente", 2: "Volume", 3: "Mix", 4: "Distribution", 5: "Prix matières", 6: "Quantité matières",
            7: "Taux MO", 8: "Rendement MO", 9: "Charges fixes"}
chrono = pont_m[pont_m["ordre"].isin(familles)].pivot_table(index="mois", columns="ordre", values="montant", aggfunc="sum")
chrono.columns = [familles[c] for c in chrono.columns]

r_reel = rent.query("version == 'Réel'")
r_bud = rent.query("version == 'Budget' and annee == @ANNEE")
cum = rent.query("annee == @ANNEE and mois <= @dernier")
rp = cum.pivot_table(index="produit", columns="version", values=["ca", "mcv"], aggfunc="sum")
gam = r_reel.pivot_table(index="gamme", columns="annee", values="mcv", aggfunc="sum") / \
      r_reel.pivot_table(index="gamme", columns="annee", values="ca", aggfunc="sum")
gam.loc["Total"] = r_reel.groupby("annee")["mcv"].sum() / r_reel.groupby("annee")["ca"].sum()

fb = fx.query("version == 'Budget' and annee == @ANNEE")
fr = fx.query("version == 'Réel' and annee == @ANNEE")
mcv_b_m = r_bud.groupby("mois")["mcv"].sum()
res_b_m = mcv_b_m - fb.groupby("mois")["montant"].sum()
mcv_a_m = pd.concat([r_reel.query("annee == @ANNEE").groupby("mois")["mcv"].sum(), prev.groupby("mois")["mcv"].sum()])
f_a_m = pd.concat([fr.groupby("mois")["montant"].sum(), prev_f.groupby("mois")["montant"].sum()])
res_a_m = mcv_a_m - f_a_m


def mcv_scen(col):
    v = prev[col]
    return (v * prev["prix_kg"] - v * prev["prix_kg"] * prev["frais_distribution"] / prev["ca"]
            - v * (prev["matieres"] + prev["main_oeuvre"]) / prev["volume_kg"]).groupby(prev["mois"]).sum()


res_bas_m = mcv_scen("volume_kg_p10") - prev_f.groupby("mois")["montant"].sum()
res_haut_m = mcv_scen("volume_kg_p90") - prev_f.groupby("mois")["montant"].sum()

cols = ["volume_kg", "ca", "frais_distribution", "matieres", "main_oeuvre", "mcv"]
att = r_reel.query("annee == @ANNEE")[cols].sum() + prev[cols].sum()
bud_an = r_bud[cols].sum()
n1 = r_reel.query("annee == @ANNEE - 1")[cols].sum()
f_att = fr["montant"].sum() + prev_f["montant"].sum()
f_n1 = fx.query("version == 'Réel' and annee == @ANNEE - 1")["montant"].sum()
res_att = att["mcv"] - f_att
res_bud_an = bud_an["mcv"] - fb["montant"].sum()
res_att_bas = res_att - res_a_m.loc[dernier + 1:].sum() + res_bas_m.sum()
res_att_haut = res_att - res_a_m.loc[dernier + 1:].sum() + res_haut_m.sum()


def point_mort(mcv_m, fixes_an, annee):
    c = 0.0
    for m, x in mcv_m.items():
        if c + x >= fixes_an:
            return date(annee, m, 1) + timedelta(days=int((fixes_an - c) / x * calendar.monthrange(annee, m)[1]))
        c += x
    return None


pm_att, pm_bud = point_mort(mcv_a_m, f_att, ANNEE), point_mort(mcv_b_m, fb["montant"].sum(), ANNEE)

vol_hist = r_reel.groupby(["annee", "mois"])["volume_kg"].sum()
vol_hist.index = pd.to_datetime([f"{a}-{m:02d}-01" for a, m in vol_hist.index])
vol_prev = prev.groupby("mois")[["volume_kg", "volume_kg_p10", "volume_kg_p90"]].sum()
vol_prev.index = pd.to_datetime([f"{ANNEE}-{m:02d}-01" for m in vol_prev.index])
vol_bud = r_bud.groupby("mois")["volume_kg"].sum()
vol_bud.index = pd.to_datetime([f"{ANNEE}-{m:02d}-01" for m in vol_bud.index])

com = []
ca_b, ca_r = v_prod["ca_b"].sum(), v_prod["ca_r"].sum()
com.append(f"Au {date_arrete:%d/%m/%Y}, le résultat d'exploitation cumulé atteint {eur(res_r_cum)} € contre {eur(res_b_cum)} € "
           f"au budget ({pfr((res_r_cum - res_b_cum) / res_b_cum)}). Le chiffre d'affaires est {'conforme' if abs(ca_r / ca_b - 1) < 0.01 else 'en écart'} "
           f"({pfr(ca_r / ca_b - 1)}) : la dégradation provient de la marge.")
ecarts = pont.iloc[1:-1].set_index("ordre")["montant"]
for o in ecarts.abs().sort_values(ascending=False).index:
    x = ecarts[o]
    if abs(x) < SEUIL:
        continue
    sens = "favorable" if x > 0 else "défavorable"
    if o == 5:
        top = mat.sort_values("prix").head(2)
        mm = em.groupby(["matiere", "mois"]).apply(lambda g: g["cout_r"].sum() / g["qte_r"].sum() / g["prix_std"].mean() - 1, include_groups=False)
        m0 = mm.loc[top.index[0]]
        debut = m0[m0 > 0.05].index.min()
        detail = " et ".join(f"{minus(LIB['matieres'][k])} {keur(r_['prix'])} (prix réel {pfr(r_['hausse'])} par rapport au standard)" for k, r_ in top.iterrows())
        com.append(f"Prix des matières : {keur(x)} ({sens}), dont {detail}."
                   + (f" La dérive du {minus(LIB['matieres'][top.index[0]])} commence en {MOIS_L[int(debut)]}." if pd.notna(debut) else ""))
    elif o == 6:
        pq = em.groupby("produit")["ecart_quantite"].sum().sort_values()
        p0 = pq.index[0]
        pm_ = em[em["produit"] == p0].groupby("mois")["ecart_quantite"].sum().sort_values().head(2).index.sort_values()
        com.append(f"Quantité de matières : {keur(x)} ({sens}), concentré sur {minus(LIB['produits'][p0])} ({keur(pq.iloc[0])}), "
                   f"surtout en {' et '.join(MOIS_L[int(m)] for m in pm_)} (surconsommation, rebuts).")
    elif o == 3:
        part = lambda g, c: ev.groupby(g)[c].sum() / ev[c].sum()
        dp = (part("produit", "vol_r") - part("produit", "vol_b")).sort_values()
        dc = (part("canal", "vol_r") - part("canal", "vol_b")).sort_values()
        com.append(f"Mix : {keur(x)} ({sens}). Le produit « {LIB['produits'][dp.index[-1]]} » gagne {num(dp.iloc[-1] * 100)} pts de part du volume "
                   f"alors que le canal {minus(LIB['canaux'][dc.index[0]])} en perd {num(-dc.iloc[0] * 100)} pts : les volumes glissent vers des ventes moins rentables.")
    elif o == 2:
        com.append(f"Volume : {keur(x)} ({sens}), avec des volumes totaux à {pfr(v_prod['vol_r'].sum() / v_prod['vol_b'].sum() - 1)} par rapport au budget.")
    elif o == 1:
        pv = ev.groupby(["produit", "canal"])["ecart_prix"].sum().sort_values()
        a_, b_ = pv.index[0], pv.index[-1]
        com.append(f"Prix de vente : {keur(x)} ({sens}). Le plus pénalisant : {minus(LIB['produits'][a_[0]])} en {minus(LIB['canaux'][a_[1]])} "
                   f"({keur(pv.iloc[0])}) ; le plus favorable : {minus(LIB['produits'][b_[0]])} en {minus(LIB['canaux'][b_[1]])} ({keur(pv.iloc[-1])}).")
    elif o == 9:
        e_ = (fix["budget"] - fix["reel"]).sort_values()
        com.append(f"Charges fixes : {keur(x)} ({sens}). Dépassements : {minus(LIB['natures_fixes'][e_.index[0]])} ({keur(e_.iloc[0])}) et "
                   f"{minus(LIB['natures_fixes'][e_.index[1]])} ({keur(e_.iloc[1])}) ; économie sur {minus(LIB['natures_fixes'][e_.index[-1]])} ({keur(e_.iloc[-1])}).")
    elif o == 7:
        t_r, t_s = emo["cout_r"].sum() / emo["heures_r"].sum(), (emo["heures_r"] * emo["taux_std"]).sum() / emo["heures_r"].sum()
        t_r, t_s = round(t_r, 2), round(t_s, 2)
        com.append(f"Taux horaire : {keur(x)} ({sens}), taux réel moyen de {num2(t_r)} €/h contre {num2(t_s)} €/h au standard ({pfr(t_r / t_s - 1)}).")
    elif o == 8:
        d_ = (mo["h_r"] / mo["h_std"] - 1).sort_values()
        com.append(f"Rendement de la main-d'œuvre : {keur(x)} ({sens}), avec une dérive des heures sur {minus(LIB['produits'][d_.index[-1]])} ({pfr(d_.iloc[-1])}).")
    else:
        com.append(f"{pont.set_index('ordre').loc[o, 'poste']} : {keur(x)} ({sens}).")
com.append(f"Atterrissage {ANNEE} : résultat estimé à {eur(res_att)} € contre {eur(res_bud_an)} € au budget ({pfr((res_att - res_bud_an) / res_bud_an)}), "
           f"dans une fourchette de {eur(res_att_bas)} € à {eur(res_att_haut)} €. Point mort projeté le {pm_att:%d/%m/%Y} (budget : {pm_bud:%d/%m/%Y}).")
taux_fd = r_reel.query("annee == @ANNEE")["frais_distribution"].sum() / ca_r
mcv_cum = r_reel.query("annee == @ANNEE")["mcv"].sum()
com.append(f"Leviers : pour combler l'écart cumulé de {eur(res_b_cum - res_r_cum)} €, il faudrait augmenter les prix de vente de "
           f"{pfr((res_b_cum - res_r_cum) / (ca_r * (1 - taux_fd)), False)} ou les volumes de {pfr((res_b_cum - res_r_cum) / mcv_cum, False)} à mix constant.")


def sauver(fig, nom):
    fig.tight_layout()
    p = GRAPH / f"{nom}.png"
    fig.savefig(p, facecolor="white")
    plt.close(fig)
    return p


fig, ax = plt.subplots(figsize=(11, 5.2))
lbl = ["Résultat\nbudgété", "Prix de\nvente", "Volume", "Mix", "Distri-\nbution", "Prix\nmatières", "Quantité\nmatières",
       "Taux\nMO", "Rende-\nment MO", "Charges\nfixes", "Résultat\nréel"]
vals = pont["montant"].values
bas, cumul = [], 0
for i, v in enumerate(vals):
    if i in (0, len(vals) - 1):
        bas.append(0)
        cumul = v
    else:
        bas.append(cumul if v >= 0 else cumul + v)
        cumul += v
hauteurs = [abs(v) if 0 < i < len(vals) - 1 else v for i, v in enumerate(vals)]
couleurs = [GRIS if i in (0, len(vals) - 1) else (BLEU if v >= 0 else ROUGE) for i, v in enumerate(vals)]
ax.bar(range(len(vals)), hauteurs, bottom=bas, color=couleurs, width=0.62, edgecolor="white", linewidth=2)
for i, (v, b, hh) in enumerate(zip(vals, bas, hauteurs)):
    t = f"{v / 1000:,.0f} k€".replace(",", " ") if i in (0, len(vals) - 1) else keur(v)
    ax.text(i, b + hh + 15_000, t, ha="center", va="bottom", fontsize=9, color=ENCRE)
ax.set_xticks(range(len(vals)), lbl, fontsize=9)
ax.yaxis.set_major_formatter(k_eur)
ax.set_ylim(0, max(b + hh for b, hh in zip(bas, hauteurs)) * 1.12)
ax.set_title(f"Du résultat budgété au résultat réel, cumul janvier-{MOIS_L[dernier]} {ANNEE}")
ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=BLEU), plt.Rectangle((0, 0), 1, 1, color=ROUGE)],
          labels=["Écart favorable", "Écart défavorable"], frameon=False, loc="upper right")
g_pont = sauver(fig, "1_pont_resultat")

fig, ax = plt.subplots(figsize=(10, 4.8))
xb = list(range(1, 13))
ax.plot(xb, res_b_m.cumsum().values, color=ENCRE2, lw=2, ls="--", label="Budget")
ca_cum = res_a_m.cumsum()
ax.plot(range(1, dernier + 1), ca_cum.loc[:dernier].values, color=BLEU, lw=2, marker="o", ms=4, label="Réel")
xp = list(range(dernier, 13))
base = ca_cum.loc[dernier]
ax.plot(xp, ca_cum.loc[dernier:].values, color=BLEU, lw=2, ls=":", marker="o", ms=4, label="Prévision")
ax.fill_between(xp, [base] + list(base + res_bas_m.cumsum().values), [base] + list(base + res_haut_m.cumsum().values),
                color=BLEU, alpha=0.15, lw=0, label="Fourchette P10-P90")
ax.set_xticks(xb, [MOIS[m] for m in xb])
ax.yaxis.set_major_formatter(k_eur)
for y, c, t in [(res_b_m.sum(), ENCRE2, "Budget"), (res_att, BLEU, "Atterrissage")]:
    ax.annotate(f"{t} : {y / 1e6:.2f} M€".replace(".", ","), (12, y), xytext=(8, 0), textcoords="offset points", va="center", color=ENCRE, fontsize=9)
ax.set_xlim(0.6, 13.8)
ax.set_title(f"Résultat d'exploitation cumulé {ANNEE} : budget et atterrissage")
ax.legend(frameon=False, loc="upper left")
g_cumul = sauver(fig, "2_resultat_cumule")

fig, ax = plt.subplots(figsize=(10, 4.8))
ax.plot(vol_hist.index, vol_hist.values / 1000, color=BLEU, lw=2, label="Réel")
der = vol_hist.index[-1]
xs = [der] + list(vol_prev.index)
ax.plot(xs, [vol_hist.iloc[-1] / 1000] + list(vol_prev["volume_kg"] / 1000), color=BLEU, lw=2, ls=":", marker="o", ms=4, label="Prévision")
ax.fill_between(xs, [vol_hist.iloc[-1] / 1000] + list(vol_prev["volume_kg_p10"] / 1000),
                [vol_hist.iloc[-1] / 1000] + list(vol_prev["volume_kg_p90"] / 1000), color=BLEU, alpha=0.15, lw=0, label="Fourchette P10-P90")
ax.plot(vol_bud.index, vol_bud.values / 1000, color=ENCRE2, lw=1.5, ls="--", label=f"Budget {ANNEE}")
ax.set_ylabel("Tonnes")
ticks = pd.date_range(vol_hist.index[0], vol_prev.index[-1], freq="6MS")
ax.set_xticks(ticks, [f"{MOIS[d.month]} {d.year}" for d in ticks])
modele = prev["modele"].iloc[0]
ax.set_title(f"Volumes mensuels 2023-{ANNEE} et prévision {MOIS[dernier + 1]}-{MOIS[12]} ({modele.split(' ')[0]})")
ax.legend(frameon=False, loc="upper left", ncol=4)
g_vol = sauver(fig, "3_prevision_volumes")

fig, ax = plt.subplots(figsize=(9, 4.8))
ordre_p = (rp["mcv"]["Réel"] / rp["ca"]["Réel"]).sort_values().index
tb = (rp["mcv"]["Budget"] / rp["ca"]["Budget"]).loc[ordre_p]
tr = (rp["mcv"]["Réel"] / rp["ca"]["Réel"]).loc[ordre_p]
y = np.arange(len(ordre_p))
ax.hlines(y, tr, tb, color=GRILLE, lw=3)
ax.scatter(tb, y, s=70, color=GRIS, zorder=3, label="Budget", edgecolor="white", linewidth=2)
ax.scatter(tr, y, s=70, color=ROUGE, zorder=3, label="Réel", edgecolor="white", linewidth=2)
for yi, a_, b_ in zip(y, tr, tb):
    ax.text(a_ - 0.004, yi, f"{a_:.1%}".replace(".", ","), ha="right", va="center", fontsize=9, color=ENCRE)
    ax.text(b_ + 0.004, yi, f"{(a_ - b_) * 100:+.1f} pts".replace(".", ","), ha="left", va="center", fontsize=9, color=ENCRE2)
ax.set_yticks(y, [LIB["produits"][p] for p in ordre_p])
ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0%}"))
ax.grid(axis="x", color=GRILLE)
ax.grid(axis="y", visible=False)
ax.set_xlim(min(tr) - 0.05, max(tb) + 0.05)
ax.set_title(f"Taux de marge sur coûts variables par produit, cumul {MOIS[dernier]} {ANNEE}")
ax.legend(frameon=False, loc="lower right")
g_prod = sauver(fig, "4_taux_mcv_produits")

fig, ax = plt.subplots(figsize=(9, 4.8))
annees = list(gam.columns)
for (g, c) in zip(["CHO", "TRA", "PRE"], [BLEU, ORANGE, VERT_EAU]):
    ax.plot(annees, gam.loc[g].values, color=c, lw=2, marker="o", ms=5, label=LIB["gammes"][g])
    ax.annotate(LIB["gammes"][g], (annees[-1], gam.loc[g].iloc[-1]), xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color=ENCRE)
ax.plot(annees, gam.loc["Total"].values, color=ENCRE2, lw=1.5, ls="--", marker="o", ms=4, label="Total")
ax.set_xticks(annees, [str(a) if a < ANNEE else f"{a}\n(jan.-{MOIS[dernier]})" for a in annees])
ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0%}"))
ax.set_xlim(annees[0] - 0.3, annees[-1] + 0.6)
ax.set_title("Taux de MCV réel par gamme : l'effet de la crise du cacao et du beurre")
ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=4)
g_gam = sauver(fig, "5_taux_mcv_gammes")

fig, ax = plt.subplots(figsize=(9, 4.8))
mo_ = mat.sort_values("prix", ascending=False)
y = np.arange(len(mo_))
ax.barh(y - 0.2, mo_["prix"], height=0.38, color=BLEU, label="Écart sur prix", edgecolor="white", linewidth=1)
ax.barh(y + 0.2, mo_["quantite"], height=0.38, color=ORANGE, label="Écart sur quantité", edgecolor="white", linewidth=1)
ax.set_yticks(y, [LIB["matieres"][m] for m in mo_.index])
ax.xaxis.set_major_formatter(k_eur)
ax.grid(axis="x", color=GRILLE)
ax.grid(axis="y", visible=False)
ax.axvline(0, color=GRIS, lw=1)
ax.set_title(f"Écarts sur matières premières, cumul {MOIS[dernier]} {ANNEE} (négatif = défavorable)")
ax.legend(frameon=False, loc="lower left")
g_mat = sauver(fig, "6_ecarts_matieres")

wb = Workbook()
POLICE = "Arial"
F_TITRE = Font(name=POLICE, size=14, bold=True, color="1F3864")
F_SOUS = Font(name=POLICE, size=10, italic=True, color="52514E")
F_SECTION = Font(name=POLICE, size=11, bold=True, color="1F3864")
F_ENTETE = Font(name=POLICE, size=10, bold=True, color="FFFFFF")
F_NORMAL = Font(name=POLICE, size=10)
F_GRAS = Font(name=POLICE, size=10, bold=True)
FILL_ENTETE = PatternFill("solid", fgColor="1F3864")
FILL_TOTAL = PatternFill("solid", fgColor="E9EEF6")
BORD = Border(top=Side(style="thin", color="1F3864"))
NF = {"eur": '#,##0;[Red]-#,##0;"-"', "pct": '0.0%;[Red]-0.0%;"-"', "pts": '+0.0" pts";[Red]-0.0" pts";"-"',
      "num": '#,##0;[Red]-#,##0;"-"', "dec": '0.00', "txt": "@", "eurkg": '0.00" €"'}


def entete_feuille(ws, titre, sous_titre):
    ws.sheet_view.showGridLines = False
    ws["A1"], ws["A2"] = titre, sous_titre
    ws["A1"].font, ws["A2"].font = F_TITRE, F_SOUS
    ws.column_dimensions["A"].width = 32


def tableau(ws, r0, titre, index, colonnes, total="Total"):
    ws.cell(r0, 1, titre).font = F_SECTION
    r = r0 + 1
    lettres = {c[0]: get_column_letter(i + 2) for i, c in enumerate(colonnes)}
    ws.cell(r, 1, "").fill = FILL_ENTETE
    for i, (nom, *_rest) in enumerate(colonnes):
        c = ws.cell(r, i + 2, nom)
        c.font, c.fill, c.alignment = F_ENTETE, FILL_ENTETE, Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[r].height = 30
    premiere = r + 1

    def formule(tpl, ligne):
        return re.sub(r"\{([^}]+)\}", lambda m: str(ligne) if m.group(1) == "r" else lettres[m.group(1)], tpl)

    for k, lib in enumerate(index):
        r += 1
        ws.cell(r, 1, lib).font = F_NORMAL
        for i, (nom, src, fmt, mode_total) in enumerate(colonnes):
            c = ws.cell(r, i + 2)
            if isinstance(src, str) and src.startswith("="):
                c.value = formule(src, r)
            else:
                v = src[k]
                c.value = None if (isinstance(v, float) and np.isnan(v)) else (float(v) if isinstance(v, (np.floating, np.integer)) else v)
            c.number_format, c.font = NF[fmt], F_NORMAL
    derniere = r
    if total:
        r += 1
        ws.cell(r, 1, total).font = F_GRAS
        for i, (nom, src, fmt, mode_total) in enumerate(colonnes):
            c = ws.cell(r, i + 2)
            L = get_column_letter(i + 2)
            if mode_total == "sum":
                c.value = f"=SUM({L}{premiere}:{L}{derniere})"
            elif mode_total == "f":
                c.value = formule(src, r)
            c.number_format, c.font = NF[fmt], F_GRAS
        for col in range(1, len(colonnes) + 2):
            ws.cell(r, col).fill, ws.cell(r, col).border = FILL_TOTAL, BORD
    return r + 2, premiere, derniere


def largeurs(ws, w=15, n=12):
    for i in range(2, n + 2):
        ws.column_dimensions[get_column_letter(i)].width = w


def image(ws, chemin, ancre, largeur=760):
    img = Image(chemin)
    ratio = largeur / img.width
    img.width, img.height = largeur, img.height * ratio
    ws.add_image(img, ancre)


ws = wb.active
ws.title = "Synthèse"
entete_feuille(ws, f"Biscuiterie Ker Avel - Reporting de gestion à fin {MOIS_L[dernier]} {ANNEE}",
               "Société et données fictives, générées pour un projet de portfolio. Montants en euros.")
largeurs(ws, 16, 9)
p_ca, p_mcv = cum.pivot_table(columns="version", values=["ca", "mcv"], aggfunc="sum").T.loc[["Budget", "Réel"]].T.values
r = 4
ws.cell(r, 1, "Indicateurs clés").font = F_SECTION
r += 1
heads = ["Budget cumul", "Réel cumul", "Écart", "Écart %", "", "Budget année", "Atterrissage", "Écart", "Écart %"]
ws.cell(r, 1).fill = FILL_ENTETE
for i, t in enumerate(heads):
    if t:
        c = ws.cell(r, i + 2, t)
        c.font, c.fill, c.alignment = F_ENTETE, FILL_ENTETE, Alignment(horizontal="center", wrap_text=True)
ws.row_dimensions[r].height = 30
f_cum_b, f_cum_r = fb.query("mois <= @dernier")["montant"].sum(), fr["montant"].sum()
lignes = [("Chiffre d'affaires", p_ca[0], p_ca[1], bud_an["ca"], att["ca"]),
          ("Marge sur coûts variables", p_mcv[0], p_mcv[1], bud_an["mcv"], att["mcv"]),
          ("Taux de MCV", None, None, None, None),
          ("Charges fixes", f_cum_b, f_cum_r, fb["montant"].sum(), f_att),
          ("Résultat d'exploitation", None, None, None, None)]
r1 = r + 1
for k, (lib, a, b, c_, d) in enumerate(lignes):
    rr = r1 + k
    ws.cell(rr, 1, lib).font = F_GRAS if lib.startswith("Résultat") else F_NORMAL
    for col, v in zip("BCGH", (a, b, c_, d)):
        cell = ws[f"{col}{rr}"]
        if lib == "Taux de MCV":
            cell.value, cell.number_format = f"=IFERROR({col}{r1 + 1}/{col}{r1},0)", NF["pct"]
        elif lib.startswith("Résultat"):
            cell.value, cell.number_format = f"={col}{r1 + 1}-{col}{r1 + 3}", NF["eur"]
        else:
            cell.value, cell.number_format = float(v), NF["eur"]
    for e, (x, y_) in (("D", ("B", "C")), ("I", ("G", "H"))):
        sgn = -1 if lib == "Charges fixes" else 1
        if lib == "Taux de MCV":
            ws[f"{e}{rr}"] = f"=({y_}{rr}-{x}{rr})*100"
            ws[f"{e}{rr}"].number_format = NF["pts"]
        else:
            ws[f"{e}{rr}"] = f"=({y_}{rr}-{x}{rr})*{sgn}"
            ws[f"{e}{rr}"].number_format = NF["eur"]
            pc = "E" if e == "D" else "J"
            ws[f"{pc}{rr}"] = f"=IFERROR({e}{rr}/ABS({x}{rr}),0)"
            ws[f"{pc}{rr}"].number_format = NF["pct"]
    for col in "BCDEGHIJ":
        ws[f"{col}{rr}"].font = F_GRAS if lib.startswith("Résultat") else F_NORMAL
    if lib.startswith("Résultat"):
        for col in "ABCDEGHIJ":
            ws[f"{col}{rr}"].fill, ws[f"{col}{rr}"].border = FILL_TOTAL, BORD
r = r1 + len(lignes)
ws.cell(r, 1, "Écarts exprimés en impact sur le résultat : positif = favorable, négatif (rouge) = défavorable.").font = F_SOUS
ws.cell(r + 1, 1, f"Point mort : projeté le {pm_att:%d/%m/%Y} (budget : {pm_bud:%d/%m/%Y}). Fourchette d'atterrissage du résultat : "
                  f"{eur(res_att_bas)} € à {eur(res_att_haut)} €.").font = F_NORMAL
r += 3
ws.cell(r, 1, f"Commentaires automatiques (écarts supérieurs à {eur(SEUIL)} €)").font = F_SECTION
for t in com:
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=10)
    c = ws.cell(r, 1, f"• {t}")
    c.font, c.alignment = F_NORMAL, Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[r].height = 15 * max(1, int(np.ceil(len(t) / 150)))
image(ws, g_pont, f"A{r + 2}", 900)

ws = wb.create_sheet("Pont du résultat")
entete_feuille(ws, "Pont du résultat budgété au résultat réel", f"Cumul janvier à {MOIS_L[dernier]} {ANNEE}. Positif = favorable.")
largeurs(ws, 16, 4)
ws.column_dimensions["A"].width = 36
r = 4
ws.cell(r, 1, "Analyse en cascade").font = F_SECTION
for i, t in enumerate(["Montant", "Sens", "Résultat cumulé"]):
    c = ws.cell(r + 1, i + 2, t)
    c.font, c.fill, c.alignment = F_ENTETE, FILL_ENTETE, Alignment(horizontal="center")
ws.cell(r + 1, 1).fill = FILL_ENTETE
r0 = r + 2
for k, row in pont.iterrows():
    rr = r0 + k
    ws.cell(rr, 1, row["poste"]).font = F_NORMAL
    if k < len(pont) - 1:
        ws.cell(rr, 2, float(row["montant"]))
        ws.cell(rr, 3, "" if k == 0 else f'=IF(B{rr}>=0,"F","D")')
        ws.cell(rr, 4, f"=B{rr}" if k == 0 else f"=D{rr - 1}+B{rr}")
    else:
        ws.cell(rr, 2, f"=SUM(B{r0}:B{rr - 1})")
        ws.cell(rr, 4, f"=B{rr}")
        for col in range(1, 5):
            ws.cell(rr, col).font, ws.cell(rr, col).fill, ws.cell(rr, col).border = F_GRAS, FILL_TOTAL, BORD
    for col in (2, 4):
        ws.cell(rr, col).number_format = NF["eur"]
    ws.cell(rr, 3).alignment = Alignment(horizontal="center")
rr += 2
ws.cell(rr, 1, "Résultat réel issu des comptes").font = F_NORMAL
ws.cell(rr, 2, float(res_r_cum)).number_format = NF["eur"]
ws.cell(rr + 1, 1, "Contrôle de bouclage (doit être nul)").font = F_GRAS
ws.cell(rr + 1, 2, f"=ROUND(B{rr - 2}-B{rr},2)").number_format = '0.00'
ws.cell(rr + 1, 3, f'=IF(B{rr + 1}=0,"OK","ANOMALIE")').font = F_GRAS
image(ws, g_pont, "F4", 820)

ws = wb.create_sheet("Écarts ventes")
entete_feuille(ws, "Écarts sur chiffre d'affaires et marge", f"Cumul janvier à {MOIS_L[dernier]} {ANNEE}. Écarts de volume et de mix valorisés à la MCV standard.")
largeurs(ws, 14, 10)
idx = v_prod.index
r, _, _ = tableau(ws, 4, "Par produit (€)", [LIB["produits"][p] for p in idx], [
    ("CA budget", v_prod["ca_b"].values, "eur", "sum"), ("CA réel", v_prod["ca_r"].values, "eur", "sum"),
    ("Écart CA", "={CA réel}{r}-{CA budget}{r}", "eur", "f"), ("Écart prix", v_prod["prix"].values, "eur", "sum"),
    ("Écart volume", v_prod["volume"].values, "eur", "sum"), ("Écart mix", v_prod["mix"].values, "eur", "sum"),
    ("Écart marge total", "={Écart prix}{r}+{Écart volume}{r}+{Écart mix}{r}", "eur", "f"),
    ("Statut", '=IF(ABS({Écart marge total}{r})<' + str(SEUIL) + ',"Non significatif",IF({Écart marge total}{r}>0,"Favorable","Défavorable"))', "txt", None)])
ws.column_dimensions["I"].width = 18
tableau(ws, r, "Par canal", [LIB["canaux"][c] for c in v_can.index], [
    ("Tonnes budget", (v_can["vol_b"] / 1000).values, "num", "sum"), ("Tonnes réelles", (v_can["vol_r"] / 1000).values, "num", "sum"),
    ("Part budget", "={Tonnes budget}{r}/{Tonnes budget}" + str(r + 2 + len(v_can)), "pct", "f"),
    ("Part réelle", "={Tonnes réelles}{r}/{Tonnes réelles}" + str(r + 2 + len(v_can)), "pct", "f"),
    ("Écart prix", v_can["prix"].values, "eur", "sum"), ("Écart volume", v_can["volume"].values, "eur", "sum"),
    ("Écart mix", v_can["mix"].values, "eur", "sum"), ("Écart total", "={Écart prix}{r}+{Écart volume}{r}+{Écart mix}{r}", "eur", "f")])

ws = wb.create_sheet("Écarts coûts")
entete_feuille(ws, "Écarts sur coûts variables et charges fixes", f"Cumul janvier à {MOIS_L[dernier]} {ANNEE}. Coûts standards = production réelle x standards du budget.")
largeurs(ws, 14, 8)
r, _, _ = tableau(ws, 4, "Matières premières (€)", [LIB["matieres"][m] for m in mat.index], [
    ("Coût standard", mat["cout_std"].values, "eur", "sum"), ("Coût réel", mat["cout_r"].values, "eur", "sum"),
    ("Écart total", "={Coût standard}{r}-{Coût réel}{r}", "eur", "f"), ("Écart prix", mat["prix"].values, "eur", "sum"),
    ("Écart quantité", mat["quantite"].values, "eur", "sum"), ("Hausse de prix", mat["hausse"].values, "pct", None)])
r, _, _ = tableau(ws, r, "Main-d'œuvre directe", [LIB["produits"][p] for p in mo.index], [
    ("Heures standard", mo["h_std"].values, "num", "sum"), ("Heures réelles", mo["h_r"].values, "num", "sum"),
    ("Dérive heures", "=IFERROR({Heures réelles}{r}/{Heures standard}{r}-1,0)", "pct", "f"),
    ("Coût standard", mo["cout_std"].values, "eur", "sum"), ("Coût réel", mo["cout_r"].values, "eur", "sum"),
    ("Écart taux", mo["taux"].values, "eur", "sum"), ("Écart rendement", mo["rendement"].values, "eur", "sum"),
    ("Écart total", "={Écart taux}{r}+{Écart rendement}{r}", "eur", "f")])
r, _, _ = tableau(ws, r, "Charges fixes (€)", [LIB["natures_fixes"][n] for n in fix.index], [
    ("Budget", fix["budget"].values, "eur", "sum"), ("Réel", fix["reel"].values, "eur", "sum"),
    ("Écart", "={Budget}{r}-{Réel}{r}", "eur", "f"), ("Écart %", "=IFERROR({Écart}{r}/{Budget}{r},0)", "pct", "f")])
ed_c = ed.groupby("canal")[["frais_std", "frais_r"]].sum()
tableau(ws, r, "Frais de distribution (€)", [LIB["canaux"][c] for c in ed_c.index], [
    ("Frais standard", ed_c["frais_std"].values, "eur", "sum"), ("Frais réels", ed_c["frais_r"].values, "eur", "sum"),
    ("Écart", "={Frais standard}{r}-{Frais réels}{r}", "eur", "f")])
image(ws, g_mat, "J4", 640)

ws = wb.create_sheet("Rentabilité")
entete_feuille(ws, "Rentabilité et seuil de rentabilité", f"Cumul janvier à {MOIS_L[dernier]} {ANNEE}.")
largeurs(ws, 15, 8)
ip = rp.index
r, _, _ = tableau(ws, 4, "Marge sur coûts variables par produit (€)", [LIB["produits"][p] for p in ip], [
    ("CA budget", rp["ca"]["Budget"].values, "eur", "sum"), ("CA réel", rp["ca"]["Réel"].values, "eur", "sum"),
    ("MCV budget", rp["mcv"]["Budget"].values, "eur", "sum"), ("MCV réelle", rp["mcv"]["Réel"].values, "eur", "sum"),
    ("Taux budget", "=IFERROR({MCV budget}{r}/{CA budget}{r},0)", "pct", "f"),
    ("Taux réel", "=IFERROR({MCV réelle}{r}/{CA réel}{r},0)", "pct", "f"),
    ("Dérive", "=({Taux réel}{r}-{Taux budget}{r})*100", "pts", "f")])
ws.cell(r, 1, "Seuil de rentabilité").font = F_SECTION
heads = [f"Budget {ANNEE}", f"Budget cumul {MOIS[dernier]}", f"Réel cumul {MOIS[dernier]}", f"Atterrissage {ANNEE}"]
ws.cell(r + 1, 1).fill = FILL_ENTETE
for i, t in enumerate(heads):
    c = ws.cell(r + 1, i + 2, t)
    c.font, c.fill, c.alignment = F_ENTETE, FILL_ENTETE, Alignment(horizontal="center", wrap_text=True)
ws.row_dimensions[r + 1].height = 30
b = r + 2
donnees = [(bud_an["ca"], bud_an["mcv"], fb["montant"].sum()), (p_ca[0], p_mcv[0], f_cum_b), (p_ca[1], p_mcv[1], f_cum_r), (att["ca"], att["mcv"], f_att)]
lib_sr = [("Chiffre d'affaires", "eur"), ("Marge sur coûts variables", "eur"), ("Charges fixes", "eur"), ("Taux de MCV", "pct"),
          ("Résultat d'exploitation", "eur"), ("Seuil de rentabilité (CA)", "eur"), ("Marge de sécurité", "eur"),
          ("Indice de sécurité", "pct"), ("Levier opérationnel", "dec")]
for k, (lib, fmt) in enumerate(lib_sr):
    ws.cell(b + k, 1, lib).font = F_GRAS if k in (4, 5) else F_NORMAL
for j, (ca_, mcv_, f_) in enumerate(donnees):
    L = get_column_letter(j + 2)
    vals = [float(ca_), float(mcv_), float(f_), f"=IFERROR({L}{b + 1}/{L}{b},0)", f"={L}{b + 1}-{L}{b + 2}",
            f"=IFERROR({L}{b + 2}/{L}{b + 3},0)", f"={L}{b}-{L}{b + 5}", f"=IFERROR({L}{b + 6}/{L}{b},0)", f"=IFERROR({L}{b + 1}/{L}{b + 4},0)"]
    for k, v in enumerate(vals):
        c = ws.cell(b + k, j + 2, v)
        c.number_format, c.font = NF[lib_sr[k][1]], F_GRAS if k in (4, 5) else F_NORMAL
ws.cell(b + 10, 1, "Seuil = charges fixes / taux de MCV ; indice de sécurité = (CA - seuil) / CA ; levier opérationnel = MCV / résultat.").font = F_SOUS
image(ws, g_prod, "J4", 600)
image(ws, g_gam, "J28", 600)

ws = wb.create_sheet("Chronologie")
entete_feuille(ws, "Chronologie des écarts", f"Impact mensuel sur le résultat {ANNEE} (€). Positif = favorable. Échelle de couleur : rouge = défavorable, bleu = favorable.")
largeurs(ws, 13, 11)
ws.column_dimensions["A"].width = 14
r, p1, pn = tableau(ws, 4, "Écarts par mois et par nature", [MOIS_L[m].capitalize() for m in chrono.index],
                    [(c, chrono[c].values, "eur", "sum") for c in chrono.columns] +
                    [("Total", "=SUM({Prix de vente}{r}:{Charges fixes}{r})", "eur", "f")], total="Cumul")
plage = f"B{p1}:{get_column_letter(len(chrono.columns) + 1)}{pn}"
ws.conditional_formatting.add(plage, ColorScaleRule(start_type="num", start_value=-60000, start_color="E34948",
                                                    mid_type="num", mid_value=0, mid_color="FFFFFF",
                                                    end_type="num", end_value=60000, end_color="2A78D6"))

ws = wb.create_sheet("Atterrissage")
entete_feuille(ws, f"Rolling forecast et atterrissage {ANNEE}",
               f"Réel de janvier à {MOIS_L[dernier]}, prévision de {MOIS_L[dernier + 1]} à décembre (modèle : {modele}).")
largeurs(ws, 15, 8)
r, p1, pn = tableau(ws, 4, "Résultat d'exploitation mensuel (€)", [MOIS_L[m].capitalize() for m in range(1, 13)], [
    ("Type", ["Réel" if m <= dernier else "Prévision" for m in range(1, 13)], "txt", None),
    ("Budget", res_b_m.values, "eur", "sum"), ("Réel / prévision", res_a_m.values, "eur", "sum"),
    ("Écart", "={Réel / prévision}{r}-{Budget}{r}", "eur", "f")], total="Année")
for k in range(12):
    rr = p1 + k
    ws.cell(rr, 6, f"=C{rr}" if k == 0 else f"=F{rr - 1}+C{rr}").number_format = NF["eur"]
    ws.cell(rr, 7, f"=D{rr}" if k == 0 else f"=G{rr - 1}+D{rr}").number_format = NF["eur"]
    ws.cell(rr, 6).font = ws.cell(rr, 7).font = F_NORMAL
for col, t in ((6, "Cumul budget"), (7, "Cumul atterrissage")):
    c = ws.cell(p1 - 1, col, t)
    c.font, c.fill, c.alignment = F_ENTETE, FILL_ENTETE, Alignment(horizontal="center", wrap_text=True)
comp = pd.DataFrame({f"Réel {ANNEE - 1}": [n1["volume_kg"] / 1000, n1["ca"], n1["frais_distribution"], n1["matieres"], n1["main_oeuvre"], n1["mcv"], f_n1],
                     f"Budget {ANNEE}": [bud_an["volume_kg"] / 1000, bud_an["ca"], bud_an["frais_distribution"], bud_an["matieres"], bud_an["main_oeuvre"], bud_an["mcv"], fb["montant"].sum()],
                     "Atterrissage": [att["volume_kg"] / 1000, att["ca"], att["frais_distribution"], att["matieres"], att["main_oeuvre"], att["mcv"], f_att]},
                    index=["Volume (tonnes)", "Chiffre d'affaires", "Frais de distribution", "Matières", "Main-d'œuvre directe", "Marge sur coûts variables", "Charges fixes"])
r, p1, pn = tableau(ws, r, f"Compte de résultat {ANNEE} : budget et atterrissage (€)", list(comp.index), [
    (c, comp[c].values, "eur", None) for c in comp.columns] + [
    ("Écart / budget", f"={{Atterrissage}}{{r}}-{{Budget {ANNEE}}}{{r}}", "eur", None),
    ("Écart %", f"=IFERROR({{Écart / budget}}{{r}}/{{Budget {ANNEE}}}{{r}},0)", "pct", None)], total="Résultat d'exploitation")
for j, L in enumerate("BCDE"):
    ws[f"{L}{pn + 1}"] = f"={L}{pn - 1}-{L}{pn}"
    ws[f"{L}{pn + 1}"].number_format = NF["eur"]
ws[f"F{pn + 1}"] = f"=IFERROR(E{pn + 1}/ABS(C{pn + 1}),0)"
ws[f"F{pn + 1}"].number_format = NF["pct"]
ws.cell(pn + 2, 1, f"Fourchette du résultat (P10-P90 sur les volumes) : {eur(res_att_bas)} € à {eur(res_att_haut)} €. "
                   "Hypothèses : prix des 3 derniers mois, coûts unitaires du dernier mois clos, charges fixes = budget x ratio médian réel/budget.").font = F_SOUS
r = pn + 4
tableau(ws, r, f"Backtest des modèles de prévision (6 derniers mois clos)", list(bt["modele"]), [
    ("WAPE segments", bt["WAPE segments"].values, "pct", None), ("MAPE total mensuel", bt["MAPE total mensuel"].values, "pct", None),
    ("Biais", bt["Biais"].values, "pct", None)], total=None)
ws.column_dimensions["A"].width = 34
image(ws, g_cumul, "J4", 640)
image(ws, g_vol, "J28", 640)

for w in wb.worksheets:
    w.sheet_properties.tabColor = "1F3864"
    w.freeze_panes = "A4"
    w.page_setup.orientation = "landscape"
    w.page_setup.fitToWidth, w.page_setup.fitToHeight = 1, 0
    w.sheet_properties.pageSetUpPr.fitToPage = True
wb.save(fichier)

print(f"\nReporting Excel : {fichier.relative_to(BASE)}")
print(f"Graphiques ({len(list(GRAPH.glob('*.png')))}) : {GRAPH.relative_to(BASE)}")
print("\nCommentaires automatiques :")
for t in com:
    print(f"  - {t}")
