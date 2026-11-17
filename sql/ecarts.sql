DROP VIEW IF EXISTS v_pont_mensuel;
DROP VIEW IF EXISTS v_ecarts_fixes;
DROP VIEW IF EXISTS v_ecarts_mo;
DROP VIEW IF EXISTS v_ecarts_matieres;
DROP VIEW IF EXISTS v_ecarts_distribution;
DROP VIEW IF EXISTS v_ecarts_ventes;
DROP VIEW IF EXISTS v_production;
DROP VIEW IF EXISTS v_cout_std;

CREATE VIEW v_cout_std AS
WITH mat AS (
    SELECT bp.annee, bp.mois, n.produit, SUM(n.qte_std_kg * bp.prix_unitaire) AS mat_std_kg
    FROM nomenclature n
    JOIN budget_prix_matieres bp ON bp.matiere = n.matiere
    GROUP BY bp.annee, bp.mois, n.produit
)
SELECT m.annee, m.mois, m.produit, m.mat_std_kg,
       p.heures_std_tonne / 1000.0 * t.taux_horaire AS mo_std_kg
FROM mat m
JOIN produits p ON p.code = m.produit
JOIN budget_taux_mo t ON t.annee = m.annee AND t.mois = m.mois;

CREATE VIEW v_production AS
SELECT annee, mois, produit, SUM(volume_kg) AS production_kg
FROM ventes
GROUP BY annee, mois, produit;

CREATE VIEW v_ecarts_ventes AS
WITH base AS (
    SELECT b.annee, b.mois, b.produit, b.canal,
           b.volume_kg AS vol_b, b.prix_kg AS prix_b,
           v.volume_kg AS vol_r, v.ca AS ca_r,
           b.prix_kg * (1 - c.taux_frais_distribution) - s.mat_std_kg - s.mo_std_kg AS mcv_std_kg
    FROM budget_ventes b
    JOIN ventes v ON v.annee = b.annee AND v.mois = b.mois AND v.produit = b.produit AND v.canal = b.canal
    JOIN canaux c ON c.code = b.canal
    JOIN v_cout_std s ON s.annee = b.annee AND s.mois = b.mois AND s.produit = b.produit
),
fen AS (
    SELECT *,
           vol_b / SUM(vol_b) OVER (PARTITION BY annee, mois) AS mix_b,
           vol_r / SUM(vol_r) OVER (PARTITION BY annee, mois) AS mix_r,
           SUM(vol_r) OVER (PARTITION BY annee, mois) AS vol_r_total
    FROM base
)
SELECT annee, mois, produit, canal, vol_b, vol_r, prix_b,
       ca_r / NULLIF(vol_r, 0) AS prix_r,
       mix_b, mix_r, mcv_std_kg,
       vol_b * prix_b AS ca_b, ca_r,
       vol_b * mcv_std_kg AS mcv_b,
       ca_r - vol_r * prix_b AS ecart_prix,
       (vol_r_total * mix_b - vol_b) * mcv_std_kg AS ecart_volume,
       (vol_r - vol_r_total * mix_b) * mcv_std_kg AS ecart_mix
FROM fen;

CREATE VIEW v_ecarts_distribution AS
SELECT v.annee, v.mois, v.produit, v.canal,
       c.taux_frais_distribution * b.prix_kg * v.volume_kg AS frais_std,
       v.frais_distribution AS frais_r,
       c.taux_frais_distribution * b.prix_kg * v.volume_kg - v.frais_distribution AS ecart_distribution
FROM ventes v
JOIN budget_ventes b ON b.annee = v.annee AND b.mois = v.mois AND b.produit = v.produit AND b.canal = v.canal
JOIN canaux c ON c.code = v.canal;

CREATE VIEW v_ecarts_matieres AS
SELECT c.annee, c.mois, c.produit, c.matiere,
       p.production_kg * n.qte_std_kg AS qte_std,
       c.quantite AS qte_r,
       bp.prix_unitaire AS prix_std,
       c.montant / c.quantite AS prix_r,
       p.production_kg * n.qte_std_kg * bp.prix_unitaire AS cout_std,
       c.montant AS cout_r,
       c.quantite * bp.prix_unitaire - c.montant AS ecart_prix,
       (p.production_kg * n.qte_std_kg - c.quantite) * bp.prix_unitaire AS ecart_quantite
FROM consommations c
JOIN v_production p ON p.annee = c.annee AND p.mois = c.mois AND p.produit = c.produit
JOIN nomenclature n ON n.produit = c.produit AND n.matiere = c.matiere
JOIN budget_prix_matieres bp ON bp.annee = c.annee AND bp.mois = c.mois AND bp.matiere = c.matiere;

CREATE VIEW v_ecarts_mo AS
SELECT h.annee, h.mois, h.produit,
       p.production_kg / 1000.0 * pr.heures_std_tonne AS heures_std,
       h.heures AS heures_r,
       t.taux_horaire AS taux_std,
       h.cout / h.heures AS taux_r,
       p.production_kg / 1000.0 * pr.heures_std_tonne * t.taux_horaire AS cout_std,
       h.cout AS cout_r,
       h.heures * t.taux_horaire - h.cout AS ecart_taux,
       (p.production_kg / 1000.0 * pr.heures_std_tonne - h.heures) * t.taux_horaire AS ecart_rendement
FROM heures_mo h
JOIN v_production p ON p.annee = h.annee AND p.mois = h.mois AND p.produit = h.produit
JOIN produits pr ON pr.code = h.produit
JOIN budget_taux_mo t ON t.annee = h.annee AND t.mois = h.mois;

CREATE VIEW v_ecarts_fixes AS
SELECT b.annee, b.mois, b.nature,
       b.montant AS montant_b, r.montant AS montant_r,
       b.montant - r.montant AS ecart
FROM budget_charges_fixes b
JOIN charges_fixes r ON r.annee = b.annee AND r.mois = b.mois AND r.nature = b.nature;

CREATE VIEW v_pont_mensuel AS
WITH mois_reels AS (SELECT DISTINCT annee, mois FROM v_ecarts_ventes),
reel AS (
    SELECT m.annee, m.mois,
           (SELECT SUM(ca - frais_distribution) FROM ventes v WHERE v.annee = m.annee AND v.mois = m.mois)
         - (SELECT SUM(montant) FROM consommations c WHERE c.annee = m.annee AND c.mois = m.mois)
         - (SELECT SUM(cout) FROM heures_mo h WHERE h.annee = m.annee AND h.mois = m.mois)
         - (SELECT SUM(montant) FROM charges_fixes f WHERE f.annee = m.annee AND f.mois = m.mois) AS resultat
    FROM mois_reels m
)
SELECT annee, mois, 0 AS ordre, 'Résultat budgété' AS poste,
       SUM(mcv_b) - (SELECT SUM(montant) FROM budget_charges_fixes f WHERE f.annee = e.annee AND f.mois = e.mois) AS montant
FROM v_ecarts_ventes e GROUP BY annee, mois
UNION ALL SELECT annee, mois, 1, 'Écart sur prix de vente', SUM(ecart_prix) FROM v_ecarts_ventes GROUP BY annee, mois
UNION ALL SELECT annee, mois, 2, 'Écart sur volume', SUM(ecart_volume) FROM v_ecarts_ventes GROUP BY annee, mois
UNION ALL SELECT annee, mois, 3, 'Écart sur mix', SUM(ecart_mix) FROM v_ecarts_ventes GROUP BY annee, mois
UNION ALL SELECT annee, mois, 4, 'Écart sur frais de distribution', SUM(ecart_distribution) FROM v_ecarts_distribution GROUP BY annee, mois
UNION ALL SELECT annee, mois, 5, 'Écart sur prix des matières', SUM(ecart_prix) FROM v_ecarts_matieres GROUP BY annee, mois
UNION ALL SELECT annee, mois, 6, 'Écart sur quantité de matières', SUM(ecart_quantite) FROM v_ecarts_matieres GROUP BY annee, mois
UNION ALL SELECT annee, mois, 7, 'Écart sur taux horaire', SUM(ecart_taux) FROM v_ecarts_mo GROUP BY annee, mois
UNION ALL SELECT annee, mois, 8, 'Écart sur rendement MO', SUM(ecart_rendement) FROM v_ecarts_mo GROUP BY annee, mois
UNION ALL SELECT annee, mois, 9, 'Écart sur charges fixes', SUM(ecart) FROM v_ecarts_fixes GROUP BY annee, mois
UNION ALL SELECT annee, mois, 10, 'Résultat réel', resultat FROM reel;
