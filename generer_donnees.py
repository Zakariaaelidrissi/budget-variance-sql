import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

SEED = 2026
rng = np.random.default_rng(SEED)

OUT = Path(__file__).resolve().parent / "data"
DB = OUT / "biscuiterie.db"
ANNEES_HIST = [2023, 2024, 2025]
ANNEE = 2026
DERNIER_MOIS_REEL = 10

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE gammes (code TEXT PRIMARY KEY, libelle TEXT NOT NULL);
CREATE TABLE produits (code TEXT PRIMARY KEY, libelle TEXT NOT NULL, gamme TEXT NOT NULL REFERENCES gammes(code), heures_std_tonne REAL NOT NULL);
CREATE TABLE canaux (code TEXT PRIMARY KEY, libelle TEXT NOT NULL, taux_frais_distribution REAL NOT NULL);
CREATE TABLE matieres (code TEXT PRIMARY KEY, libelle TEXT NOT NULL, unite TEXT NOT NULL);
CREATE TABLE nomenclature (produit TEXT REFERENCES produits(code), matiere TEXT REFERENCES matieres(code), qte_std_kg REAL NOT NULL, PRIMARY KEY (produit, matiere));
CREATE TABLE natures_fixes (code TEXT PRIMARY KEY, libelle TEXT NOT NULL);
CREATE TABLE budget_ventes (annee INTEGER, mois INTEGER, produit TEXT REFERENCES produits(code), canal TEXT REFERENCES canaux(code), volume_kg REAL NOT NULL, prix_kg REAL NOT NULL, PRIMARY KEY (annee, mois, produit, canal));
CREATE TABLE budget_prix_matieres (annee INTEGER, mois INTEGER, matiere TEXT REFERENCES matieres(code), prix_unitaire REAL NOT NULL, PRIMARY KEY (annee, mois, matiere));
CREATE TABLE budget_taux_mo (annee INTEGER, mois INTEGER, taux_horaire REAL NOT NULL, PRIMARY KEY (annee, mois));
CREATE TABLE budget_charges_fixes (annee INTEGER, mois INTEGER, nature TEXT REFERENCES natures_fixes(code), montant REAL NOT NULL, PRIMARY KEY (annee, mois, nature));
CREATE TABLE ventes (annee INTEGER, mois INTEGER, produit TEXT REFERENCES produits(code), canal TEXT REFERENCES canaux(code), volume_kg REAL NOT NULL, ca REAL NOT NULL, frais_distribution REAL NOT NULL, PRIMARY KEY (annee, mois, produit, canal));
CREATE TABLE consommations (annee INTEGER, mois INTEGER, produit TEXT REFERENCES produits(code), matiere TEXT REFERENCES matieres(code), quantite REAL NOT NULL, montant REAL NOT NULL, PRIMARY KEY (annee, mois, produit, matiere));
CREATE TABLE heures_mo (annee INTEGER, mois INTEGER, produit TEXT REFERENCES produits(code), heures REAL NOT NULL, cout REAL NOT NULL, PRIMARY KEY (annee, mois, produit));
CREATE TABLE charges_fixes (annee INTEGER, mois INTEGER, nature TEXT REFERENCES natures_fixes(code), montant REAL NOT NULL, PRIMARY KEY (annee, mois, nature));
CREATE INDEX ix_ventes_periode ON ventes (annee, mois);
CREATE INDEX ix_conso_periode ON consommations (annee, mois);
"""

GAMMES = {"TRA": "Tradition", "CHO": "Chocolat", "PRE": "Premium"}
PRODUITS = {
    "GAL": ("Galette pur beurre", "TRA", 18, 900_000, 6.20, (0.70, 0.20, 0.10)),
    "PAL": ("Palet breton", "TRA", 20, 500_000, 7.10, (0.60, 0.20, 0.20)),
    "SAB": ("Sablé tout chocolat", "CHO", 22, 450_000, 8.60, (0.55, 0.15, 0.30)),
    "COO": ("Cookie pépites de chocolat", "CHO", 24, 400_000, 9.10, (0.55, 0.15, 0.30)),
    "COF": ("Coffret assortiment", "PRE", 80, 120_000, 16.50, (0.50, 0.10, 0.40)),
    "DEN": ("Crêpe dentelle", "PRE", 55, 150_000, 12.40, (0.40, 0.25, 0.35)),
}
CANAUX = {"GMS": ("Grande distribution", 0.04, 1.00), "CHR": ("Grossistes et CHR", 0.06, 1.10), "EXP": ("Export", 0.09, 1.18)}
MATIERES = {"FAR": ("Farine de blé", "kg"), "BEU": ("Beurre AOP", "kg"), "SUC": ("Sucre", "kg"),
            "CHC": ("Chocolat de couverture", "kg"), "OEU": ("Œufs liquides", "kg"), "EMB": ("Emballage", "u")}
NOMENCLATURE = {
    "GAL": {"FAR": 0.45, "BEU": 0.25, "SUC": 0.25, "OEU": 0.08, "EMB": 5},
    "PAL": {"FAR": 0.40, "BEU": 0.30, "SUC": 0.24, "OEU": 0.10, "EMB": 4},
    "SAB": {"FAR": 0.38, "BEU": 0.22, "SUC": 0.22, "CHC": 0.18, "EMB": 5},
    "COO": {"FAR": 0.35, "BEU": 0.20, "SUC": 0.22, "CHC": 0.25, "OEU": 0.06, "EMB": 6},
    "COF": {"FAR": 0.35, "BEU": 0.28, "SUC": 0.20, "CHC": 0.12, "OEU": 0.07, "EMB": 12},
    "DEN": {"FAR": 0.30, "BEU": 0.15, "SUC": 0.35, "CHC": 0.10, "OEU": 0.10, "EMB": 8},
}
PRIX_MAT = {
    "FAR": {2023: 0.62, 2024: 0.52, 2025: 0.53, "B": 0.55},
    "BEU": {2023: 6.40, 2024: 6.90, 2025: 7.10, "B": 7.20},
    "SUC": {2023: 0.95, 2024: 0.90, 2025: 0.82, "B": 0.85},
    "CHC": {2023: 6.20, 2024: 8.40, 2025: 9.30, "B": 9.50},
    "OEU": {2023: 3.40, 2024: 3.00, 2025: 3.10, "B": 3.20},
    "EMB": {2023: 0.110, 2024: 0.115, 2025: 0.118, "B": 0.120},
}
TAUX_MO = {2023: 29.50, 2024: 30.40, 2025: 31.20, "B": 32.00}
NATURES = {"PER": ("Personnel de structure", 2_000_000), "LOY": ("Loyers et crédit-bail", 600_000),
           "AMO": ("Dotations aux amortissements", 1_100_000), "ENE": ("Énergie", 900_000),
           "MAI": ("Maintenance", 420_000), "MKT": ("Marketing et publicité", 650_000), "FGX": ("Frais généraux", 700_000)}
TENDANCE = {2023: 0.94, 2024: 0.97, 2025: 1.00, ANNEE: 1.03}
NIVEAU_PRIX = {2023: 1 / 1.02 ** 3, 2024: 1 / 1.02 ** 2, 2025: 1 / 1.02, ANNEE: 1.0}
NIVEAU_FIXES = {2023: 0.91, 2024: 0.94, 2025: 0.97, ANNEE: 1.0}

SAISON = np.array([0.80, 0.82, 0.92, 0.95, 0.92, 0.85, 0.75, 0.72, 0.98, 1.08, 1.25, 1.46])
SAISON_COF = np.array([0.30, 0.50, 0.40, 0.60, 0.30, 0.20, 0.20, 0.20, 0.40, 1.20, 3.50, 4.20])
SAISON_MKT = np.array([0.6, 0.6, 0.8, 0.9, 0.8, 0.6, 0.4, 0.4, 1.2, 1.6, 2.0, 2.1])
SAISON_ENE = np.array([1.25, 1.20, 1.05, 0.95, 0.85, 0.80, 0.75, 0.75, 0.90, 1.05, 1.20, 1.25])
norm = lambda s: s / s.mean()
SAISON, SAISON_COF, SAISON_MKT, SAISON_ENE = map(norm, (SAISON, SAISON_COF, SAISON_MKT, SAISON_ENE))

SCENARIO = [
    (2, 3, "Ventes", "Promotion GMS sur la gamme Tradition : prix -7 %, volumes +15 %", "Écart prix défavorable, écart volume favorable"),
    (1, 10, "Ventes", "Galettes en forte demande en GMS : volumes +10 %", "Écart de mix défavorable (produit à faible marge)"),
    (5, 10, "Ventes", "Hausse tarifaire GMS de 3 % sur la gamme Chocolat", "Écart prix favorable"),
    (6, 10, "Ventes", "Perte d'un distributeur britannique : volumes export Chocolat et Dentelle -30 %", "Écart volume défavorable, mix défavorable"),
    (1, 10, "Matières", "Chocolat de couverture +8 % (crise du cacao)", "Écart prix matières défavorable"),
    (4, 10, "Matières", "Envolée du beurre : +15 % à partir d'avril", "Écart prix matières défavorable"),
    (8, 9, "Matières", "Panne de la ligne Cookies : rebuts, consommations +9 % sur les Cookies", "Écart quantité matières défavorable"),
    (1, 10, "Main-d'œuvre", "Augmentation salariale (NAO) de 3,8 % contre 2,5 % budgétés", "Écart taux défavorable"),
    (8, 9, "Main-d'œuvre", "Panne de la ligne Cookies : heures +25 % sur les Cookies", "Écart rendement défavorable"),
    (10, 10, "Main-d'œuvre", "Heures supplémentaires pour préparer le pic de Noël : taux +6 %", "Écart taux défavorable"),
    (1, 10, "Distribution", "Surcoût carburant à l'export : frais 9,6 % du CA au lieu de 9 %", "Frais variables défavorables"),
    (8, 9, "Charges fixes", "Réparation de la ligne Cookies : maintenance +75 k€", "Charges fixes défavorables"),
    (9, 10, "Charges fixes", "Campagne de lancement de Noël : marketing +60 k€", "Charges fixes défavorables"),
    (1, 10, "Charges fixes", "Renégociation du contrat d'énergie : -5 %", "Charges fixes favorables"),
]

periodes = [(a, m) for a in ANNEES_HIST for m in range(1, 13)] + [(ANNEE, m) for m in range(1, DERNIER_MOIS_REEL + 1)]


def saison(p, m):
    return (SAISON_COF if p == "COF" else SAISON)[m - 1]


def prix_base(p, c, a):
    return PRODUITS[p][4] * CANAUX[c][2] * NIVEAU_PRIX[a]


def bruit(s, n=None):
    return rng.normal(1, s, n)


budget_ventes = [(ANNEE, m, p, c, round(PRODUITS[p][3] * TENDANCE[ANNEE] * PRODUITS[p][5][i] * saison(p, m) / 12),
                  round(prix_base(p, c, ANNEE), 2))
                 for m in range(1, 13) for p in PRODUITS for i, c in enumerate(CANAUX)]
budget_prix = [(ANNEE, m, k, v["B"]) for m in range(1, 13) for k, v in PRIX_MAT.items()]
budget_taux = [(ANNEE, m, TAUX_MO["B"]) for m in range(1, 13)]


def fixe_mensuel(n, total, m):
    s = SAISON_MKT if n == "MKT" else SAISON_ENE if n == "ENE" else np.ones(12)
    return total / 12 * s[m - 1]


budget_fixes = [(ANNEE, m, n, round(fixe_mensuel(n, t, m), 2)) for m in range(1, 13) for n, (_, t) in NATURES.items()]


def effets_ventes(a, m, p, c):
    fv, fp = 1.0, 1.0
    if a != ANNEE:
        return fv, fp
    g = PRODUITS[p][1]
    if c == "GMS" and g == "TRA" and m in (2, 3):
        fv, fp = fv * 1.15, fp * 0.93
    if c == "GMS" and p == "GAL":
        fv *= 1.10
    if c == "GMS" and g == "CHO" and m >= 5:
        fp *= 1.03
    if c == "EXP" and (g == "CHO" or p == "DEN") and m >= 6:
        fv *= 0.70
    return fv, fp


ventes = []
for a, m in periodes:
    for p in PRODUITS:
        for i, c in enumerate(CANAUX):
            fv, fp = effets_ventes(a, m, p, c)
            vol = round(PRODUITS[p][3] * TENDANCE[a] * PRODUITS[p][5][i] * saison(p, m) / 12 * fv * bruit(0.05))
            prix = prix_base(p, c, a) * fp * bruit(0.012)
            ca = round(vol * prix, 2)
            taux = CANAUX[c][1] * (1 + (0.6 / 9 if c == "EXP" and a == ANNEE else 0)) * bruit(0.03)
            ventes.append((a, m, p, c, vol, ca, round(ca * taux, 2)))
df_ventes = pd.DataFrame(ventes, columns=["annee", "mois", "produit", "canal", "volume_kg", "ca", "frais_distribution"])
production = df_ventes.groupby(["annee", "mois", "produit"])["volume_kg"].sum()


def prix_reel(k, a, m):
    if a != ANNEE:
        return PRIX_MAT[k][a] * bruit(0.015)
    b = PRIX_MAT[k]["B"]
    f = {"FAR": 0.98, "SUC": 0.99, "OEU": 1.015, "EMB": 1.01, "CHC": 1.08}.get(k, 1.0)
    if k == "BEU":
        f = 1.15 if m >= 4 else 1.007
    return b * f * bruit(0.01)


prix_mois = {(a, m, k): prix_reel(k, a, m) for a, m in periodes for k in MATIERES}

conso = []
for (a, m, p), q in production.items():
    panne = a == ANNEE and p == "COO" and m in (8, 9)
    for k, std in NOMENCLATURE[p].items():
        qte = round(q * std * rng.normal(1.01, 0.015) * (1.09 if panne and k != "EMB" else 1.0), 1)
        conso.append((a, m, p, k, qte, round(qte * prix_mois[(a, m, k)], 2)))

heures = []
for (a, m, p), q in production.items():
    if a == ANNEE:
        taux = TAUX_MO["B"] * 1.038 / 1.025 * (1.06 if m == 10 else 1.0)
    else:
        taux = TAUX_MO[a]
    h = round(q / 1000 * PRODUITS[p][2] * rng.normal(1.015, 0.03) * (1.25 if a == ANNEE and p == "COO" and m in (8, 9) else 1.0), 1)
    heures.append((a, m, p, h, round(h * taux * bruit(0.005), 2)))

fixes = []
for a, m in periodes:
    for n, (_, t) in NATURES.items():
        x = fixe_mensuel(n, t * NIVEAU_FIXES[a], m) * bruit(0.03 if n not in ("AMO", "LOY") else 0.002)
        if a == ANNEE:
            x *= 0.95 if n == "ENE" else 1.0
            x += {("MAI", 8): 45_000, ("MAI", 9): 30_000, ("MKT", 9): 25_000, ("MKT", 10): 35_000}.get((n, m), 0)
        fixes.append((a, m, n, round(x, 2)))

OUT.mkdir(exist_ok=True)
DB.unlink(missing_ok=True)
with sqlite3.connect(DB) as cx:
    cx.executescript(SCHEMA)
    ins = lambda t, rows: cx.executemany(f"INSERT INTO {t} VALUES ({','.join('?' * len(rows[0]))})", rows)
    ins("gammes", list(GAMMES.items()))
    ins("produits", [(k, v[0], v[1], v[2]) for k, v in PRODUITS.items()])
    ins("canaux", [(k, v[0], v[1]) for k, v in CANAUX.items()])
    ins("matieres", [(k, *v) for k, v in MATIERES.items()])
    ins("nomenclature", [(p, k, q) for p, d in NOMENCLATURE.items() for k, q in d.items()])
    ins("natures_fixes", [(k, v[0]) for k, v in NATURES.items()])
    ins("budget_ventes", budget_ventes)
    ins("budget_prix_matieres", budget_prix)
    ins("budget_taux_mo", budget_taux)
    ins("budget_charges_fixes", budget_fixes)
    ins("ventes", ventes)
    ins("consommations", conso)
    ins("heures_mo", heures)
    ins("charges_fixes", fixes)
    tables = [r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid")]
    comptes = {t: cx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    synthese = pd.read_sql("""
        WITH bv AS (
            SELECT bv.*, c.taux_frais_distribution AS tfd, p.heures_std_tonne AS hst
            FROM budget_ventes bv JOIN canaux c ON c.code = bv.canal JOIN produits p ON p.code = bv.produit
            WHERE bv.annee = :a AND bv.mois <= :m
        )
        SELECT 'Budget' AS version,
               (SELECT SUM(volume_kg * prix_kg) FROM bv) AS ca,
               (SELECT SUM(volume_kg * prix_kg * tfd) FROM bv) AS fd,
               (SELECT SUM(bv.volume_kg * n.qte_std_kg * bpm.prix_unitaire) FROM bv
                  JOIN nomenclature n ON n.produit = bv.produit
                  JOIN budget_prix_matieres bpm ON bpm.annee = bv.annee AND bpm.mois = bv.mois AND bpm.matiere = n.matiere) AS mat,
               (SELECT SUM(bv.volume_kg / 1000.0 * bv.hst * t.taux_horaire) FROM bv
                  JOIN budget_taux_mo t ON t.annee = bv.annee AND t.mois = bv.mois) AS mo,
               (SELECT SUM(montant) FROM budget_charges_fixes WHERE annee = :a AND mois <= :m) AS fixes
        UNION ALL
        SELECT 'Réel',
               (SELECT SUM(ca) FROM ventes WHERE annee = :a AND mois <= :m),
               (SELECT SUM(frais_distribution) FROM ventes WHERE annee = :a AND mois <= :m),
               (SELECT SUM(montant) FROM consommations WHERE annee = :a AND mois <= :m),
               (SELECT SUM(cout) FROM heures_mo WHERE annee = :a AND mois <= :m),
               (SELECT SUM(montant) FROM charges_fixes WHERE annee = :a AND mois <= :m)
    """, cx, params={"a": ANNEE, "m": DERNIER_MOIS_REEL})

pd.DataFrame(SCENARIO, columns=["mois_debut", "mois_fin", "domaine", "evenement", "effet_attendu"]).to_csv(
    OUT / "scenario_2026.csv", sep=";", index=False, encoding="utf-8-sig")

s = synthese.set_index("version")
s["mcv"] = s["ca"] - s["fd"] - s["mat"] - s["mo"]
s["resultat"] = s["mcv"] - s["fixes"]
s["taux_mcv"] = s["mcv"] / s["ca"]
fmt = lambda x: f"{x:>14,.0f}".replace(",", " ")

print(f"\nBase créée : {DB.name}")
for t, n in comptes.items():
    print(f"  {t:<22}{n:>7,}".replace(",", " "))
print(f"\nCumul janvier-{['', 'janv.', 'févr.', 'mars', 'avril', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'][DERNIER_MOIS_REEL]} {ANNEE} (€)")
print(f"{'':<26}{'Budget':>14}{'Réel':>14}{'Écart':>14}")
for lib, col in [("Chiffre d'affaires", "ca"), ("Frais de distribution", "fd"), ("Matières", "mat"), ("Main-d'œuvre directe", "mo"),
                 ("Marge sur coûts variables", "mcv"), ("Charges fixes", "fixes"), ("Résultat d'exploitation", "resultat")]:
    b, r = s.loc["Budget", col], s.loc["Réel", col]
    print(f"{lib:<26}{fmt(b)}{fmt(r)}{fmt(r - b)}")
print(f"{'Taux de MCV':<26}{s.loc['Budget', 'taux_mcv']:>14.1%}{s.loc['Réel', 'taux_mcv']:>14.1%}")
ca_an = sum(v * p for *_, v, p in budget_ventes)
print(f"\nCA budget annuel {ANNEE} : {ca_an:,.0f} €".replace(",", " "))
print(f"Historique des ventes : janvier 2023 à {DERNIER_MOIS_REEL:02d}/{ANNEE} ({len(periodes)} mois)")
print(f"Scénario 2026 ({len(SCENARIO)} événements) : scenario_2026.csv")
print(f"\nFichiers dans : {OUT}")
