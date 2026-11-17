import sqlite3
import calendar
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "biscuiterie.db"
SQL = [BASE / "sql" / "ecarts.sql", BASE / "sql" / "rentabilite.sql"]
ANNEE = 2026
MOIS = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
eur = lambda x: f"{x:,.0f}".replace(",", " ")
pct = "{:.1%}".format


def titre(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def afficher(df, pcts=(), autres=None):
    fm = {c: (pct if c in pcts else eur) for c in df.columns}
    fm.update(autres or {})
    print(df.to_string(formatters=fm))


def point_mort(mcv_mensuelle, fixes_annuelles, annee):
    cumul = 0.0
    for m, x in mcv_mensuelle.items():
        if cumul + x >= fixes_annuelles:
            jours = calendar.monthrange(annee, m)[1]
            j = (fixes_annuelles - cumul) / x * jours
            return date(annee, m, 1) + timedelta(days=int(j)), 0.0
        cumul += x
    return None, fixes_annuelles - cumul


def indicateurs(ca, mcv, fixes):
    taux = mcv / ca
    sr = fixes / taux
    res = mcv - fixes
    return {"Chiffre d'affaires": ca, "Marge sur coûts variables": mcv, "Taux de MCV": taux, "Charges fixes": fixes,
            "Résultat d'exploitation": res, "Seuil de rentabilité (CA)": sr, "Marge de sécurité": ca - sr,
            "Indice de sécurité": (ca - sr) / ca, "Levier opérationnel": mcv / res if res else float("nan")}


with sqlite3.connect(DB) as cx:
    for f in SQL:
        cx.executescript(f.read_text(encoding="utf-8"))
    r = pd.read_sql("SELECT * FROM v_rentabilite", cx)
    fx = pd.read_sql("SELECT * FROM v_charges_fixes", cx)
    lib = dict(cx.execute("SELECT code, libelle FROM produits").fetchall())
    lib_c = dict(cx.execute("SELECT code, libelle FROM canaux").fetchall())
    lib_g = dict(cx.execute("SELECT code, libelle FROM gammes").fetchall())
    beurre_choc = dict(cx.execute(
        "SELECT matiere, SUM(montant) FROM consommations WHERE annee = ? AND matiere IN ('BEU', 'CHC') GROUP BY matiere",
        (ANNEE,)).fetchall())

dernier = r.query("version == 'Réel' and annee == @ANNEE")["mois"].max()
cols = ["volume_kg", "ca", "frais_distribution", "matieres", "main_oeuvre", "mcv"]
cum = r.query("annee == @ANNEE and mois <= @dernier")

titre(f"RENTABILITÉ PAR PRODUIT - cumul janvier à {MOIS[dernier]} {ANNEE}")
p = cum.pivot_table(index="produit", columns="version", values=["ca", "mcv", "volume_kg"], aggfunc="sum")
t = pd.DataFrame({
    "CA budget": p["ca"]["Budget"], "CA réel": p["ca"]["Réel"],
    "MCV budget": p["mcv"]["Budget"], "MCV réelle": p["mcv"]["Réel"],
    "Taux budget": p["mcv"]["Budget"] / p["ca"]["Budget"], "Taux réel": p["mcv"]["Réel"] / p["ca"]["Réel"],
    "MCV/kg réelle": p["mcv"]["Réel"] / p["volume_kg"]["Réel"],
    "Poids MCV": p["mcv"]["Réel"] / p["mcv"]["Réel"].sum(),
}).sort_values("Taux réel", ascending=False)
t["Dérive (pts)"] = (t["Taux réel"] - t["Taux budget"]) * 100
t.index = t.index.map(lib)
afficher(t, pcts=("Taux budget", "Taux réel", "Poids MCV"),
         autres={"MCV/kg réelle": "{:.2f} €".format, "Dérive (pts)": "{:+.1f}".format})

titre(f"TAUX DE MCV RÉEL PAR PRODUIT ET PAR CANAL - cumul {MOIS[dernier]} {ANNEE}")
reel = cum[cum["version"] == "Réel"]
mat = reel.pivot_table(index="produit", columns="canal", values="mcv", aggfunc="sum") / \
      reel.pivot_table(index="produit", columns="canal", values="ca", aggfunc="sum")
tot_c = reel.groupby("canal")[["mcv", "ca"]].sum()
mat.loc["Total"] = tot_c["mcv"] / tot_c["ca"]
mat.index = [lib.get(i, i) for i in mat.index]
mat.columns = [lib_c[c] for c in mat.columns]
print(mat.to_string(float_format=pct))

titre("ÉVOLUTION DU TAUX DE MCV RÉEL PAR GAMME (2026 : janvier à " + MOIS[dernier] + ")")
h = r[r["version"] == "Réel"]
hg = h.pivot_table(index="gamme", columns="annee", values="mcv", aggfunc="sum") / \
     h.pivot_table(index="gamme", columns="annee", values="ca", aggfunc="sum")
ht = h.groupby("annee")[["mcv", "ca"]].sum()
hg.loc["Total"] = ht["mcv"] / ht["ca"]
hg.index = [lib_g.get(i, i) for i in hg.index]
print(hg.to_string(float_format=pct))

titre("SEUIL DE RENTABILITÉ ET POINT MORT")
fb = fx.query("version == 'Budget' and annee == @ANNEE")
fr = fx.query("version == 'Réel'")
rb = r.query("version == 'Budget' and annee == @ANNEE")
s_budget_an = rb[cols].sum()
s_budget_cum = cum[cum["version"] == "Budget"][cols].sum()
s_reel_cum = reel[cols].sum()
ind = pd.DataFrame({
    f"Budget {ANNEE} (année)": indicateurs(s_budget_an["ca"], s_budget_an["mcv"], fb["montant"].sum()),
    f"Budget cumul {MOIS[dernier]}": indicateurs(s_budget_cum["ca"], s_budget_cum["mcv"],
                                                fb.query("mois <= @dernier")["montant"].sum()),
    f"Réel cumul {MOIS[dernier]}": indicateurs(s_reel_cum["ca"], s_reel_cum["mcv"],
                                              fr.query("annee == @ANNEE")["montant"].sum()),
})
print(f"{'':<30}" + "".join(f"{c:>24}" for c in ind.columns))
for i, row in ind.iterrows():
    f = pct if i in ("Taux de MCV", "Indice de sécurité") else "{:.2f}".format if i == "Levier opérationnel" else eur
    print(f"{i:<30}" + "".join(f"{f(x):>24}" for x in row))

print("\nPoint mort (date à laquelle la MCV cumulée couvre les charges fixes de l'année) :")
for a in sorted(h["annee"].unique()):
    mcv_m = h[h["annee"] == a].groupby("mois")["mcv"].sum()
    fixes_an = fr[fr["annee"] == a]["montant"].sum()
    if a == ANNEE:
        fixes_an += fb.query("mois > @dernier")["montant"].sum()
    d, manque = point_mort(mcv_m, fixes_an, a)
    lib_a = f"Réel {a}"
    print(f"  {lib_a:<14}{d.strftime('%d/%m/%Y') if d else f'non atteint au {calendar.monthrange(a, dernier)[1]}/{dernier:02d}/{a} : il manque {eur(manque)} € de MCV'}")
d_b, _ = point_mort(rb.groupby("mois")["mcv"].sum(), fb["montant"].sum(), ANNEE)
print(f"  {'Budget ' + str(ANNEE):<14}{d_b.strftime('%d/%m/%Y')}")

titre(f"SENSIBILITÉ DU RÉSULTAT - réel cumul {MOIS[dernier]} {ANNEE}")
res_r = ind.iloc[:, 2]["Résultat d'exploitation"]
res_b = ind.iloc[:, 1]["Résultat d'exploitation"]
taux_fd = s_reel_cum["frais_distribution"] / s_reel_cum["ca"]
sens = pd.Series({
    "Prix de vente +1 %": s_reel_cum["ca"] * 0.01 * (1 - taux_fd),
    "Volumes +1 % (mix constant)": s_reel_cum["mcv"] * 0.01,
    "Prix du beurre -10 %": beurre_choc.get("BEU", 0) * 0.10,
    "Prix du chocolat -10 %": beurre_choc.get("CHC", 0) * 0.10,
    "Taux horaire +1 %": -s_reel_cum["main_oeuvre"] * 0.01,
    "Charges fixes -1 %": fr.query("annee == @ANNEE")["montant"].sum() * 0.01,
})
for k, v in sens.items():
    print(f"  {k:<30}{eur(v):>12} €   {v / res_r:+.1%} du résultat")
ecart = res_b - res_r
print(f"\nPour retrouver le résultat budgété ({eur(res_b)} €), il faudrait :")
print(f"  soit une hausse des prix de vente de {ecart / (s_reel_cum['ca'] * (1 - taux_fd)):.1%}")
print(f"  soit une hausse des volumes de {ecart / s_reel_cum['mcv']:.1%} à mix constant")
print("\nVues SQL enregistrées : v_rentabilite, v_charges_fixes")
