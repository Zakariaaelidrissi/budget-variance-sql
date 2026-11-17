DROP VIEW IF EXISTS v_charges_fixes;
DROP VIEW IF EXISTS v_rentabilite;

CREATE VIEW v_rentabilite AS
WITH conso AS (
    SELECT annee, mois, produit, SUM(montant) AS montant
    FROM consommations
    GROUP BY annee, mois, produit
),
reel AS (
    SELECT 'Réel' AS version, v.annee, v.mois, v.produit, v.canal, v.volume_kg, v.ca,
           v.frais_distribution,
           v.volume_kg * c.montant / p.production_kg AS matieres,
           v.volume_kg * h.cout / p.production_kg AS main_oeuvre
    FROM ventes v
    JOIN v_production p ON p.annee = v.annee AND p.mois = v.mois AND p.produit = v.produit
    JOIN conso c ON c.annee = v.annee AND c.mois = v.mois AND c.produit = v.produit
    JOIN heures_mo h ON h.annee = v.annee AND h.mois = v.mois AND h.produit = v.produit
),
budget AS (
    SELECT 'Budget', b.annee, b.mois, b.produit, b.canal, b.volume_kg,
           b.volume_kg * b.prix_kg,
           b.volume_kg * b.prix_kg * c.taux_frais_distribution,
           b.volume_kg * s.mat_std_kg,
           b.volume_kg * s.mo_std_kg
    FROM budget_ventes b
    JOIN canaux c ON c.code = b.canal
    JOIN v_cout_std s ON s.annee = b.annee AND s.mois = b.mois AND s.produit = b.produit
),
u AS (SELECT * FROM reel UNION ALL SELECT * FROM budget)
SELECT u.*, p.gamme,
       ca - frais_distribution - matieres - main_oeuvre AS mcv
FROM u
JOIN produits p ON p.code = u.produit;

CREATE VIEW v_charges_fixes AS
SELECT 'Réel' AS version, annee, mois, nature, montant FROM charges_fixes
UNION ALL
SELECT 'Budget', annee, mois, nature, montant FROM budget_charges_fixes;
