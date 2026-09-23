# Dossier `assets/` — images de la page de garde

Ces images sont utilisées par la page de garde (`chapters/page_de_garde.tex`).
Elles sont **déjà en place** ; remplacez un fichier (même nom) pour le mettre à jour.

| Fichier            | Usage                                                        |
| ------------------ | ----------------------------------------------------------- |
| `background.png`   | Fond plein page (vagues rouges) couvrant toute la couverture. |
| `logo_ensa.png`    | Logo / emblème de l'ENSA Oujda (centre de l'en-tête).        |
| `entete_fr.png`    | Bandeau français (Royaume du Maroc … Oujda), à gauche.       |
| `entete_arabe.png` | Bandeau arabe, à droite de l'en-tête.                        |

> Les inclusions sont protégées par `\IfFileExists` : si une image manque,
> la couverture compile tout de même (avec un espace réservé).
