# Mini-projet EXIOBASE — Mines, UE14 (2026)

Ce dépôt rassemble le support d’un mini-projet étudiant consacré à l’analyse entrées–sorties multirégionale avec **EXIOBASE** et à l’étude d’empreintes environnementales. Le notebook explore notamment les matrices intermédiaires et de demande finale, les satellites environnementaux, l’endogénéisation du capital et une visualisation en diagramme de Sankey.

> **État du dépôt.** Le notebook est un support de travail pédagogique : il contient des exercices et des pistes de projet, ainsi que des cellules exploratoires. Toutes les cellules ne constituent pas nécessairement un pipeline exécutable de bout en bout.

## Contenu

- `exiobase_io.py` — chargement, mise en cache et préparation des tables EXIOBASE ; extraction de satellites ; calculs liés à la matrice de capital `Kbar` et à la formation nette de capital.
- `footprint_sankey.py` — lecture des tables de concordance, calcul de flux d’empreinte et génération/export d’un Sankey Plotly.
- `Exiobase_MinesUE14MiniProjet_2026.ipynb` — notebook de référence et support pédagogique.

## Pré-requis et installation

Le code a été écrit pour Python 3 et le notebook a été enregistré avec Jupyter Notebook **3.12.2**. Aucune version minimale explicite de Python n’est déclarée dans les fichiers ; Python 3.10+ est recommandé pour l’environnement du projet.

Installation des dépendances importées par les scripts :

```bash
python -m venv .venv
source .venv/bin/activate       # Windows : .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install numpy pandas scipy pyarrow pycountry country-converter openpyxl plotly jupyter
```

Dépendances optionnelles :

```bash
# Export PNG/PDF/SVG/JPG/WEBP via Plotly/Kaleido
python -m pip install kaleido
```

- `pymrio` n’est **pas importé** par les fichiers fournis et n’est donc pas requis par ce dépôt tel quel.
- `plotly` est importé de façon tolérante dans `footprint_sankey.py`, mais il est nécessaire pour appeler `make_sankey`.
- `scipy`, `pyarrow`, `country-converter`, `pycountry` et `openpyxl` sont utilisés dans certains chemins d’exécution, notamment pour `Kbar`, les fichiers Feather, les conversions de pays et les fichiers Excel.

## Données attendues

Les données ne sont pas incluses dans ce dépôt. Le notebook utilise par défaut `DATA_FOLDER = "Data/"`, `YEAR = 2019` et `SYSTEM = "pxp"`.

### Archive EXIOBASE principale

Le notebook attend :

```text
Data/Source files/IOT_2019_pxp.zip
```

`exiobase_io.py` extrait cette archive et met en cache les fichiers suivants dans :

```text
Data/EXIO3/IOT_2019_pxp/
├── Z.feather
├── A.feather
├── Y.feather
└── x.feather
```

L’archive doit contenir les fichiers tabulaires `Z.txt`, `Y.txt`, `x.txt` et `A.txt` (éventuellement dans un unique sous-dossier). Les tableaux sont lus comme des tables indexées par niveaux région/secteur, avec une structure multi-index compatible avec le code.

Le notebook ouvre également l’archive :

```text
Data/Source files/IOT_2019_ixi.zip
```

pour lire, pour chaque satellite, `unit.txt`. Les satellites explicitement listés sont : `air_emissions`, `employment`, `energy`, `factor_inputs`, `land`, `material`, `nutrients` et `water`.

### Tables satellites

Pour charger un satellite, le code attend dans le dossier Feather/EXIOBASE extrait :

```text
Data/EXIO3/IOT_2019_pxp/<satellite>/F.txt
Data/EXIO3/IOT_2019_pxp/<satellite>/F_Y.txt   # facultatif dans extract_satellites
```

Le notebook sélectionne notamment l’indicateur : `Energy use - Final` dans le satellite `energy`. Les indicateurs disponibles doivent être vérifiés dans les `unit.txt` de l’archive correspondante.

### Endogénéisation du capital

Le notebook utilise par défaut la méthode `nowcasting`, avec :

```text
Data/Source files/Kbar_exio_v3_6_2015pxp.mat
```

La clé MATLAB attendue est `KbarCfc`. Pour la méthode `from_x`, le code prévoit aussi une archive/version EXIOBASE `v3.8.2`, un fichier `.mat` contenant la clé `Kbar` et, selon les paramètres, un chemin vers cette archive et ce fichier. Les résultats mis en cache sont écrits dans `Data/Kbar/`, par exemple :

```text
Kbar_nowcasting_2019_pxp_base2015.feather
Kbar_from_x_2019_pxp_v3.8.2.feather
Kbar_from_CFC_2019_pxp_v3.8.2.feather
```

L’option `nowcasting` peut utiliser les fichiers suivants, s’ils sont disponibles :

```text
Data/World Bank/CFC worldbank.xlsx
Data/World Bank/GFCF worldbank.xlsx
```

Ces fichiers sont lus avec `header=3`, index `Country Code`, et des colonnes d’années (notamment `2015` et `2019`).

### Concordances pour le Sankey

Le notebook attend :

```text
Data/Concordance_Tables/concordance.xlsx
```

Les feuilles exploitées sont notamment `region prod`, `sector prod`, `sector cons`, `final consumption` et `cpi final`; une feuille de demande finale peut être fournie via l’argument `fd_sheet` de `load_maps`.

### Source EXIOBASE

Les fichiers fournis ne contiennent pas de lien de téléchargement ni de référence Zenodo explicite. Il faut donc compléter, dans le dépôt, la source officielle et la version effectivement utilisée avant diffusion aux étudiants. Les noms de fichiers et dossiers ci-dessus doivent rester cohérents avec les chemins codés dans le notebook.

## Démarrage rapide

Depuis la racine du dépôt, après avoir placé les données dans `Data/` :

```bash
jupyter notebook Exiobase_MinesUE14MiniProjet_2026.ipynb
# ou
jupyter lab Exiobase_MinesUE14MiniProjet_2026.ipynb
```

### Charger les tables EXIOBASE

```python
import exiobase_io as exio

resultats = exio.generate_exiobase(
    "Data/", 2019, "pxp",
    exio_path_zip="Data/Source files/IOT_2019_pxp.zip",
    re_import_exiobase=True,
    endogenise_capital=False,
    indicator=None,
    satellite=None,
)

Z = resultats["Z"]
A = resultats["A"]
Y = resultats["Y"]
x = resultats["x"]
```

`generate_exiobase` retourne un dictionnaire avec les clés `Z`, `A`, `Y`, `x`, `F`, `F_Y` et `Kbar`. Lorsque `endogenise_capital=False`, `Kbar` vaut `None`.

Pour charger l’indicateur énergétique utilisé dans le notebook :

```python
F, F_Y = exio.load_sattelite_selection(
    "Data/", 2019, "pxp",
    indicator="Energy use - Final",
    satellite="energy",
)
```

### Calculer et exporter un Sankey

```python
from footprint_sankey import (
    load_maps, compute_footprint_flows, make_sankey, save_sankey,
)

maps = load_maps("Data/Concordance_Tables/concordance.xlsx")
selection = {r"^Energy use - Final": "Final energy use"}

res = compute_footprint_flows(
    A, Y, x, F, F_Y, selection,
    target_regions=["FR"],
    region_map=maps["region"],
    sector_map=maps["sector"],
    fd_map=maps["fd"],
    cons_map=maps["cons"],
    target_label="France",
    drop_empty_exports=True,
)

fig = make_sankey(
    res,
    title="France — empreinte énergétique",
    unit="TJ",
    min_industry_share=0.01,
)
save_sankey(fig, "Results/france_sankey.html")
```

`save_sankey` produit un HTML interactif. Les formats image (`.png`, `.pdf`, `.svg`, `.jpg`, `.jpeg`, `.webp`) nécessitent Kaleido. Le tableau de liens peut aussi être exporté avec `export_link_table(res, "Results/flows.csv")` ou vers un fichier Excel.

## Fonctions publiques

### `exiobase_io.py`

- `iso3_to_iso2(code)` : convertit un code pays ISO3 en ISO2, avec quelques correspondances manuelles pour les régions EXIOBASE.
- `load_kbar(path, key)` : lit une matrice MATLAB et construit un DataFrame indexé par région et secteur.
- `setup_exiobase_tables(exio_path_zip, folder, label='newest', re_import_exiobase=False)` : extrait une archive EXIOBASE et écrit `Z`, `Y`, `x` et `A` au format Feather.
- `get_x_v382(...)` : charge ou extrait uniquement `x.txt` d’une archive/version EXIOBASE v3.8.2.
- `load_matrices(...)` : lit `Z`, `A`, `Y` et `x`, avec construction préalable depuis une archive si nécessaire.
- `calculate_kbar_from_x(Kbar_v382, x_v382, x)` : adapte `Kbar` à partir des vecteurs de production `x`.
- `calculate_kbar_from_cfc(Kbar_v382, CFC_new)` : adapte `Kbar` à partir de la consommation de capital fixe.
- `get_kbar(mat_path, key, out_path, ref_index, re_import_exiobase=False)` : charge une matrice `.mat`, la met en cache en Feather et vérifie ses labels.
- `kbar_result_path(...)` : construit le chemin de cache selon la méthode et l’année.
- `audit_wb_mapping(...)` : audite la correspondance des lignes World Bank vers les régions EXIOBASE et peut exporter le tableau d’audit.
- `calculate_kbar_from_coefficients(...)` : calcule une matrice `Kbar` par coefficients, avec possibilité de redimensionnement à partir de données World Bank.
- `calculate_Y_with_NFCF(Y, Kbar, save_path=None)` : remplace la formation brute de capital fixe par une formation nette et renvoie aussi un journal de calcul.
- `extract_satellites(...)` : lit `F.txt` et, s’il existe, `F_Y.txt` pour un satellite ; peut sélectionner certains indicateurs.
- `load_sattelite_selection(...)` : raccourci de sélection d’un indicateur satellite (nom conservé tel quel dans le code).
- `generate_exiobase(...)` : point d’entrée principal ; charge les tables, traite éventuellement le capital et charge le satellite demandé.

### `footprint_sankey.py`

- `load_maps(path, fd_sheet=None)` : lit les concordances Excel de régions, secteurs, demande finale et besoins finaux.
- `compute_footprint_flows(...)` : calcule la table de flux d’empreinte en cinq colonnes, avec contrôles de bilan et diagnostics.
- `make_sankey(...)` : construit la figure Sankey Plotly, regroupe les petits secteurs et applique les couleurs fournies.
- `save_sankey(fig, path, scale=2)` : exporte une figure selon l’extension du chemin.
- `export_link_table(res, path)` : exporte la table de liens en CSV ou Excel.

## Structure recommandée du dépôt

```text
.
├── README.md
├── exiobase_io.py
├── footprint_sankey.py
├── Exiobase_MinesUE14MiniProjet_2026.ipynb
├── Data/                         # à fournir séparément ; à ne pas versionner si volumineux
│   ├── Source files/
│   ├── EXIO3/
│   ├── Concordance_Tables/
│   ├── Kbar/
│   └── World Bank/
└── Results/                      # sorties locales du notebook
```

Il est recommandé d’ajouter les gros fichiers de données à `.gitignore` et de documenter leur provenance, leur version et leur somme de contrôle dans un fichier séparé.

## Travail étudiant

Les consignes explicites actuellement présentes dans le notebook sont :

1. **Exercice** — calculer les imports Chine → UE27 pour les produits industriels EXIOBASE et les quantifier en termes monétaires, d’énergie finale et de GES (`CO2`, `N2O`, `CH4`).
2. **Projet** — quantifier un vecteur `Y` de demande finale pour les indicateurs utilisés dans les *Decent Living Energy*.

Le notebook développe ensuite des hypothèses autour de la population, des ménages, de l’énergie, de la nutrition, du logement, de l’hygiène, de l’habillement, de la santé, de l’éducation, de la communication et de la mobilité. Ils sont destinés à aider à démarrer le projet.


## Licence et contact

Licence : Ce projet est concédé sous licence selon les termes de la licence MIT.

Contact pédagogique : vincent.d-herbemont@ifpen.fr / vincedh@gmail.com.

Référence de la base EXIOBASE et lien de téléchargement : https://exiobase.eu / https://zenodo.org/records/15689391 / https://zenodo.org/records/7073276 (for Capital use matrice)
