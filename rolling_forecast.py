import sqlite3
import calendar
import warnings
import numpy as np
import pandas as pd
from datetime import date, timedelta
from pathlib import Path
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.statespace.sarimax import SARIMAX

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "biscuiterie.db"
SQL = [BASE / "sql" / "ecarts.sql", BASE / "sql" / "rentabilite.sql"]
ANNEE = 2026
TEST = 6
MOIS = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]

pd.set_option("display.width", 200)
eur = lambda x: f"{x:,.0f}".replace(",", " ")
pct = "{:.1%}".format


def titre(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def naif_saisonnier(s, h):
    croissance = s.iloc[-12:].sum() / s.iloc[-24:-12].sum()
    idx = pd.date_range(s.index[-1] + pd.offsets.MonthBegin(), periods=h, freq="MS")
    prev = s.iloc[-12:-12 + h].values * croissance if h < 12 else s.iloc[-12:].values * croissance
    return pd.DataFrame({"prev": prev, "p10": np.nan, "p90": np.nan}, index=idx)


def ets(s, h):
    res = ETSModel(s, error="mul", trend="add", damped_trend=True, seasonal="mul", seasonal_periods=12).fit(disp=False)
    f = res.get_prediction(start=len(s), end=len(s) + h - 1).summary_frame(alpha=0.2)
    return pd.DataFrame({"prev": f["mean"].values, "p10": f["pi_lower"].values, "p90": f["pi_upper"].values}, index=f.index)


def sarima(s, h):
    res = SARIMAX(np.log(s), order=(1, 0, 0), seasonal_order=(0, 1, 1, 12), trend="c").fit(disp=False)
    f = res.get_forecast(h).summary_frame(alpha=0.2)
    return pd.DataFrame({"prev": np.exp(f["mean"]).values, "p10": np.exp(f["mean_ci_lower"]).values,
                         "p90": np.exp(f["mean_ci_upper"]).values}, index=f.index)


MODELES = {"Naïf saisonnier": naif_saisonnier, "ETS (Holt-Winters amorti)": ets, "SARIMA (1,0,0)(0,1,1)12": sarima}


def point_mort(mcv_mensuelle, fixes_annuelles, annee):
    cumul = 0.0
    for m, x in mcv_mensuelle.items():
        if cumul + x >= fixes_annuelles:
            j = (fixes_annuelles - cumul) / x * calendar.monthrange(annee, m)[1]
            return date(annee, m, 1) + timedelta(days=int(j))
        cumul += x
    return None


with sqlite3.connect(DB) as cx:
    for f in SQL:
        cx.executescript(f.read_text(encoding="utf-8"))
    ventes = pd.read_sql("SELECT * FROM ventes", cx)
    rent = pd.read_sql("SELECT * FROM v_rentabilite", cx)
    fixes = pd.read_sql("SELECT * FROM v_charges_fixes", cx)
    lib = dict(cx.execute("SELECT code, libelle FROM produits").fetchall())

ventes["date"] = pd.to_datetime(dict(year=ventes["annee"], month=ventes["mois"], day=1))
series = {k: g.set_index("date")["volume_kg"].asfreq("MS") for k, g in ventes.groupby(["produit", "canal"])}
fin = ventes["date"].max()
dernier = fin.month
h = 12 - dernier

titre(f"1. BACKTEST : prévision des {TEST} derniers mois clos à partir des données antérieures")
perf = {}
for nom, fn in MODELES.items():
    err = []
    for (p, c), s in series.items():
        reel = s.iloc[-TEST:]
        prev = fn(s.iloc[:-TEST], TEST)["prev"]
        err.append(pd.DataFrame({"produit": p, "canal": c, "reel": reel.values, "prev": prev.values}, index=reel.index))
    e = pd.concat(err)
    tot = e.groupby(level=0)[["reel", "prev"]].sum()
    perf[nom] = {"WAPE segments": (e["reel"] - e["prev"]).abs().sum() / e["reel"].sum(),
                 "MAPE total mensuel": ((tot["reel"] - tot["prev"]).abs() / tot["reel"]).mean(),
                 "Biais": tot["prev"].sum() / tot["reel"].sum() - 1}
perf = pd.DataFrame(perf).T
print(perf.to_string(formatters={c: (lambda x: f"{x:+.1%}") if c == "Biais" else pct for c in perf.columns}))
choix = perf["WAPE segments"].idxmin()
print(f"\nModèle retenu (plus faible WAPE) : {choix}")
print("WAPE : erreur absolue pondérée par les volumes, sur 18 séries produit x canal.")

prev = []
for (p, c), s in series.items():
    f = MODELES[choix](s, h)
    if f["p10"].isna().all():
        w = perf.loc[choix, "WAPE segments"]
        f["p10"], f["p90"] = f["prev"] * (1 - 1.28 * w), f["prev"] * (1 + 1.28 * w)
    prev.append(f.assign(produit=p, canal=c))
prev = pd.concat(prev).rename_axis("date").reset_index()
prev["annee"], prev["mois"] = prev["date"].dt.year, prev["date"].dt.month

r_reel = rent.query("version == 'Réel'")
recent = r_reel[(r_reel["annee"] == ANNEE) & (r_reel["mois"] > dernier - 3)]
prix = recent.groupby(["produit", "canal"]).apply(lambda g: g["ca"].sum() / g["volume_kg"].sum()).rename("prix_kg")
taux_fd = recent.groupby("canal").apply(lambda g: g["frais_distribution"].sum() / g["ca"].sum()).rename("taux_fd")
der = r_reel[(r_reel["annee"] == ANNEE) & (r_reel["mois"] == dernier)].groupby("produit")[["matieres", "main_oeuvre", "volume_kg"]].sum()
couts = pd.DataFrame({"mat_kg": der["matieres"] / der["volume_kg"], "mo_kg": der["main_oeuvre"] / der["volume_kg"]})

prev = prev.join(prix, on=["produit", "canal"]).join(taux_fd, on="canal").join(couts, on="produit")
for col in ("prev", "p10", "p90"):
    sfx = "" if col == "prev" else f"_{col}"
    v = prev[col]
    prev[f"volume_kg{sfx}"] = v
    prev[f"ca{sfx}"] = v * prev["prix_kg"]
    prev[f"mcv{sfx}"] = prev[f"ca{sfx}"] * (1 - prev["taux_fd"]) - v * (prev["mat_kg"] + prev["mo_kg"])
prev["frais_distribution"] = prev["ca"] * prev["taux_fd"]
prev["matieres"] = prev["volume_kg"] * prev["mat_kg"]
prev["main_oeuvre"] = prev["volume_kg"] * prev["mo_kg"]

fb = fixes.query("version == 'Budget' and annee == @ANNEE")
fr = fixes.query("version == 'Réel' and annee == @ANNEE")
ratio = fr.merge(fb, on=["annee", "mois", "nature"], suffixes=("_r", "_b")).assign(
    ratio=lambda d: d["montant_r"] / d["montant_b"]).groupby("nature")["ratio"].median()
fixes_prev = fb[fb["mois"] > dernier].assign(montant=lambda d: d["montant"] * d["nature"].map(ratio))

titre(f"2. PRÉVISION DES VOLUMES {MOIS[dernier + 1]}-{MOIS[12]} {ANNEE} par produit (tonnes)")
bud = rent.query("version == 'Budget' and annee == @ANNEE and mois > @dernier").groupby("produit")["volume_kg"].sum()
n1 = r_reel.query("annee == @ANNEE - 1 and mois > @dernier").groupby("produit")["volume_kg"].sum()
vp = prev.groupby("produit")[["volume_kg", "volume_kg_p10", "volume_kg_p90"]].sum()
tv = pd.DataFrame({"Réel N-1": n1, "Budget": bud, "Prévision": vp["volume_kg"], "Bas (P10)": vp["volume_kg_p10"],
                   "Haut (P90)": vp["volume_kg_p90"]}) / 1000
tv.loc["Total"] = tv.sum()
tv["Prév. / budget"] = tv["Prévision"] / tv["Budget"] - 1
tv.index = [lib.get(i, i) for i in tv.index]
print(tv.to_string(formatters={**{c: eur for c in tv.columns[:-1]}, "Prév. / budget": "{:+.1%}".format}))

cols = ["volume_kg", "ca", "frais_distribution", "matieres", "main_oeuvre", "mcv"]
reel_ytd = r_reel.query("annee == @ANNEE")[cols].sum()
att = reel_ytd + prev[cols].sum()
budget_an = rent.query("version == 'Budget' and annee == @ANNEE")[cols].sum()
n1_an = r_reel.query("annee == @ANNEE - 1")[cols].sum()
f_att = fr["montant"].sum() + fixes_prev["montant"].sum()
f_n1 = fixes.query("version == 'Réel' and annee == @ANNEE - 1")["montant"].sum()


def compte(s, f):
    return {"Volume (tonnes)": s["volume_kg"] / 1000, "Chiffre d'affaires": s["ca"], "Frais de distribution": s["frais_distribution"],
            "Matières": s["matieres"], "Main-d'œuvre directe": s["main_oeuvre"], "Marge sur coûts variables": s["mcv"],
            "Taux de MCV": s["mcv"] / s["ca"], "Charges fixes": f, "Résultat d'exploitation": s["mcv"] - f}


titre(f"3. ATTERRISSAGE {ANNEE} : réel janvier-{MOIS[dernier]} + prévision {MOIS[dernier + 1]}-{MOIS[12]} (€)")
tab = pd.DataFrame({f"Réel {ANNEE - 1}": compte(n1_an, f_n1), f"Budget {ANNEE}": compte(budget_an, fb["montant"].sum()),
                    "Atterrissage": compte(att, f_att)})
tab["Écart / budget"] = tab["Atterrissage"] - tab[f"Budget {ANNEE}"]
tab["Écart %"] = tab["Écart / budget"] / tab[f"Budget {ANNEE}"].abs()
print(f"{'':<28}" + "".join(f"{c:>16}" for c in tab.columns))
for i, row in tab.iterrows():
    if i == "Taux de MCV":
        vals = [pct(x) for x in row[:3]] + [f"{row.iloc[3] * 100:+.1f} pts", ""]
    else:
        vals = [eur(x) for x in row[:4]] + [f"{row.iloc[4]:+.1%}"]
    print(f"{i:<28}" + "".join(f"{v:>16}" for v in vals))

res_bas = att["mcv"] - prev["mcv"].sum() + prev["mcv_p10"].sum() - f_att
res_haut = att["mcv"] - prev["mcv"].sum() + prev["mcv_p90"].sum() - f_att
print(f"\nFourchette de résultat (P10-P90 sur les volumes) : {eur(res_bas)} € à {eur(res_haut)} €")
print(f"Hypothèses : prix moyens des 3 derniers mois, coûts unitaires du mois de {MOIS[dernier]},")
print("charges fixes = budget x ratio médian réel/budget de l'année (neutralise les dépenses ponctuelles).")

mcv_m = pd.concat([r_reel.query("annee == @ANNEE").groupby("mois")["mcv"].sum(), prev.groupby("mois")["mcv"].sum()])
d_att = point_mort(mcv_m, f_att, ANNEE)
d_bud = point_mort(rent.query("version == 'Budget' and annee == @ANNEE").groupby("mois")["mcv"].sum(), fb["montant"].sum(), ANNEE)
print(f"\nPoint mort projeté : {d_att.strftime('%d/%m/%Y') if d_att else 'non atteint en ' + str(ANNEE)}"
      f"  (budget : {d_bud.strftime('%d/%m/%Y')}, soit {(d_att - d_bud).days if d_att else '-'} jours de retard)")

titre("4. RÉSULTAT MENSUEL : budget, réel (R) et prévision (P) (€)")
res_b = rent.query("version == 'Budget' and annee == @ANNEE").groupby("mois")["mcv"].sum() - fb.groupby("mois")["montant"].sum()
f_m = pd.concat([fr.groupby("mois")["montant"].sum(), fixes_prev.groupby("mois")["montant"].sum()])
res_a = mcv_m - f_m
mens = pd.DataFrame({"Type": ["R" if m <= dernier else "P" for m in res_a.index], "Budget": res_b, "Réel / prévision": res_a,
                     "Écart": res_a - res_b, "Cumul budget": res_b.cumsum(), "Cumul atterrissage": res_a.cumsum()})
mens.index = [MOIS[m] for m in mens.index]
print(mens.to_string(formatters={c: eur for c in mens.columns if c != "Type"}))

sortie = prev[["annee", "mois", "produit", "canal", "volume_kg", "volume_kg_p10", "volume_kg_p90", "prix_kg", "ca",
               "frais_distribution", "matieres", "main_oeuvre", "mcv"]].assign(modele=choix, date_prevision=str(date.today()))
with sqlite3.connect(DB) as cx:
    sortie.to_sql("previsions", cx, if_exists="replace", index=False)
    fixes_prev[["annee", "mois", "nature", "montant"]].to_sql("previsions_charges_fixes", cx, if_exists="replace", index=False)
    perf.rename_axis("modele").reset_index().to_sql("backtest_modeles", cx, if_exists="replace", index=False)
print("\nTables enregistrées dans la base : previsions, previsions_charges_fixes, backtest_modeles")
