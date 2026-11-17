import sqlite3
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "biscuiterie.db"
SQL = BASE / "sql" / "ecarts.sql"
ANNEE = 2026
MOIS = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
eur = lambda x: f"{x:,.0f}".replace(",", " ")


def titre(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def tableau(df):
    print(df.to_string(float_format=eur))


with sqlite3.connect(DB) as cx:
    cx.executescript(SQL.read_text(encoding="utf-8"))
    q = lambda s: pd.read_sql(s, cx, params={"a": ANNEE})
    pont_m = q("SELECT * FROM v_pont_mensuel WHERE annee = :a")
    ventes = q("""
        SELECT p.libelle AS produit, SUM(ca_b) AS ca_budget, SUM(ca_r) AS ca_reel,
               SUM(ecart_prix) AS prix, SUM(ecart_volume) AS volume, SUM(ecart_mix) AS mix,
               SUM(ecart_prix + ecart_volume + ecart_mix) AS total
        FROM v_ecarts_ventes e JOIN produits p ON p.code = e.produit
        WHERE annee = :a GROUP BY p.code ORDER BY total""")
    canaux = q("""
        SELECT c.libelle AS canal, SUM(vol_b) / 1000 AS tonnes_budget, SUM(vol_r) / 1000 AS tonnes_reel,
               SUM(ecart_prix) AS prix, SUM(ecart_volume) AS volume, SUM(ecart_mix) AS mix
        FROM v_ecarts_ventes e JOIN canaux c ON c.code = e.canal
        WHERE annee = :a GROUP BY c.code ORDER BY c.code""")
    matieres = q("""
        SELECT m.libelle AS matiere, SUM(cout_std) AS cout_standard, SUM(cout_r) AS cout_reel,
               SUM(ecart_prix) AS prix, SUM(ecart_quantite) AS quantite,
               SUM(cout_r) / SUM(qte_r) / AVG(prix_std) - 1 AS hausse_prix
        FROM v_ecarts_matieres e JOIN matieres m ON m.code = e.matiere
        WHERE annee = :a GROUP BY m.code ORDER BY prix + quantite""")
    mo = q("""
        SELECT p.libelle AS produit, SUM(heures_std) AS h_standard, SUM(heures_r) AS h_reelles,
               SUM(ecart_taux) AS taux, SUM(ecart_rendement) AS rendement,
               SUM(heures_r) / SUM(heures_std) - 1 AS derive_heures
        FROM v_ecarts_mo e JOIN produits p ON p.code = e.produit
        WHERE annee = :a GROUP BY p.code ORDER BY taux + rendement""")
    fixes = q("""
        SELECT n.libelle AS nature, SUM(montant_b) AS budget, SUM(montant_r) AS reel, SUM(ecart) AS ecart
        FROM v_ecarts_fixes e JOIN natures_fixes n ON n.code = e.nature
        WHERE annee = :a GROUP BY n.code ORDER BY ecart""")

dernier = pont_m["mois"].max()
pont = pont_m.groupby(["ordre", "poste"], as_index=False)["montant"].sum().set_index("poste")["montant"]
bouclage = pont.iloc[:-1].sum() - pont.iloc[-1]

titre(f"PONT DU RÉSULTAT BUDGÉTÉ AU RÉSULTAT RÉEL - cumul janvier à {MOIS[dernier]} {ANNEE} (€)")
for poste, x in pont.items():
    sens = "" if poste.startswith("Résultat") else ("F" if x >= 0 else "D")
    print(f"{'-' * 60}\n" if poste == "Résultat réel" else "", end="")
    print(f"{poste:<38}{eur(x):>16}  {sens}")
ecart_total = pont.iloc[-1] - pont.iloc[0]
print(f"\nÉcart total : {eur(ecart_total)} € ({ecart_total / pont.iloc[0]:+.1%})")
print(f"Contrôle de bouclage : {abs(bouclage):.2f} € {'(OK)' if abs(bouclage) < 1 else '(ANOMALIE)'}")
print("F = favorable, D = défavorable")

titre("ÉCARTS SUR CHIFFRE D'AFFAIRES ET MARGE - par produit (€)")
tableau(ventes.set_index("produit"))
titre("ÉCARTS SUR MARGE - par canal")
tableau(canaux.set_index("canal"))

titre("ÉCARTS SUR MATIÈRES (€)")
m = matieres.set_index("matiere")
print(m.to_string(formatters={**{c: eur for c in m.columns[:-1]}, "hausse_prix": "{:+.1%}".format}))

titre("ÉCARTS SUR MAIN-D'ŒUVRE DIRECTE")
o = mo.set_index("produit")
print(o.to_string(formatters={**{c: eur for c in o.columns[:-1]}, "derive_heures": "{:+.1%}".format}))

titre("ÉCARTS SUR CHARGES FIXES (€)")
tableau(fixes.set_index("nature"))

familles = {1: "Prix vente", 2: "Volume", 3: "Mix", 4: "Distrib.", 5: "Prix mat.", 6: "Qté mat.", 7: "Taux MO", 8: "Rdt MO", 9: "Fixes"}
mens = pont_m[pont_m["ordre"].isin(familles)].pivot_table(index="mois", columns="ordre", values="montant", aggfunc="sum")
mens.columns = [familles[c] for c in mens.columns]
mens["Total"] = mens.sum(axis=1)
mens.index = [MOIS[i] for i in mens.index]
titre("CHRONOLOGIE DES ÉCARTS - par mois (€, + = favorable)")
tableau(mens)

print(f"\nVues SQL enregistrées dans {DB.name} : v_cout_std, v_production, v_ecarts_ventes, v_ecarts_distribution,")
print("v_ecarts_matieres, v_ecarts_mo, v_ecarts_fixes, v_pont_mensuel")
