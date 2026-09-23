# Compilation du rapport

Le PDF compilé est déjà fourni : **`rapport.pdf`** (45 pages).

Pour le recompiler à partir des sources, deux options (aucune installation
permanente n'est requise) :

## Option 1 — Overleaf (recommandée, zéro installation)
1. Créer un nouveau projet vide sur <https://www.overleaf.com>.
2. Téléverser **tout le dossier `rapport/`** (`rapport.tex`, `chapters/`,
   `figures/`, `references.bib`).
3. Dans *Menu → Settings*, choisir le compilateur **pdfLaTeX** ou **XeLaTeX**
   (les deux fonctionnent).
4. Compiler : Overleaf gère automatiquement BibTeX.

## Option 2 — Tectonic (ligne de commande, sans distribution TeX)
[Tectonic](https://tectonic-typesetting.github.io) est un moteur LaTeX
autonome : un seul binaire, télécharge ses paquets à la volée.

```bash
# Récupérer le binaire (ex. macOS arm64) depuis les releases GitHub :
#   https://github.com/tectonic-typesetting/tectonic/releases
# puis, dans ce dossier :
tectonic rapport.tex
```

## Structure des sources
```
rapport/
├── rapport.tex              # fichier maître (préambule + métadonnées)
├── chapters/                # page de garde, liminaires, chapitres, annexes
├── figures/                 # captures d'écran + graphiques (PNG)
├── references.bib           # bibliographie
└── rapport.pdf              # PDF compilé
```

## Personnalisation
Les métadonnées (établissement, filière, auteurs, encadrant, année) sont
définies sous forme de macros `\newcommand` en tête de `rapport.tex` et sont
faciles à modifier.
