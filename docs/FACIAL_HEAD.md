# Visage humanoïde expérimental

L’option **Améliorer le visage** utilise MediaPipe et TOPOS-DiT pour traiter automatiquement la tête depuis la T-pose. Elle vise Windows Desktop, TRELLIS.2 mono-image, un humanoïde de face, la résolution 1024 et les matériaux PBR natifs. Elle est décochée par défaut. Sur l’installation de test, le composant occupe environ **4,1 Go** en plus de TRELLIS et des rendus enregistrés.

## Essayer

1. Dans le dossier de cette version de Studio, ouvrir **Installer le module visage.cmd**. Une installation TRELLIS.2 fonctionnelle et son encodeur de géométrie pour les matériaux 1024 sont requis. L’installateur vérifie les téléchargements et exécute une reconstruction de tête sur le GPU avant de déclarer le composant prêt.
2. Dans **Créer**, sélectionner l’image, **TRELLIS.2 · Image unique**, **Humanoïde**, **1024** et **PBR natif**. Dans les réglages avancés, cocher **Améliorer le visage (expérimental)**. Les finitions qui reconstruisent ensuite toute la surface et la régénération de matériaux sont incompatibles avec cette option.
3. Comparer le nouveau modèle avec la génération ordinaire, en gardant la même référence, la même graine et le même profil. Dans **Comparer**, choisir **Cadrer les visages** pour centrer les deux caméras sur les yeux. Examiner le bord des paupières, l’implant, le nez et la bouche de face puis de trois quarts.

Le traitement détecte 478 repères dans le portrait recadré et prédit un maillage de tête. Il ajuste le relief à l’avant du visage et crée les ouvertures des paupières. La peau et les lèvres reçoivent la couleur de la référence pendant l’unique calcul des matériaux, avant la création de la texture UV. La rugosité et la brillance viennent du matériau PBR. Le GLB comprend deux globes oculaires distincts, chacun avec son pivot. La couleur des iris est estimée sur l’image quand elle est suffisamment détaillée. Le regard et les clignements animés demandent un rig approprié. Une entrée trop petite, de profil ou masquée limite la fidélité. Un échec d’ajustement est indiqué dans la tâche.

Les yeux restent des objets distincts dans le GLB exporté. Les outils qui exigent une transformation commune à tous les maillages peuvent refuser ce fichier, notamment la projection de textures, la copie jeu précalculée et UltraTex sur maillage existant. Utiliser le modèle témoin si l’un de ces parcours est nécessaire.

## Revenir en arrière

- Pour la génération suivante, décocher **Améliorer le visage**. Les générations expérimentales sont des modèles distincts de la collection.
- Pour retirer les poids, les dépendances et les caches facultatifs, ouvrir **Desinstaller le module visage.cmd**. Le composant possède son dossier `.tools/facial-head`. Le désinstalleur vérifie son marqueur de propriété et protège les opérations en cours. Il fonctionne aussi après une installation interrompue.
- Une fois le composant retiré, actualiser la page. Les GLB déjà exportés restent autonomes. Chaque modèle d’essai peut être retiré individuellement depuis la collection.

Depuis le dossier de l’application, le script `installer/install_facial_head.py` accepte `install`, `status` et `remove` avec le Python de Studio. La demande REST de génération accepte `facial_head_enhancement: true`. Si ce champ est absent, la génération ordinaire est utilisée.

## Dépendances et licences

Les sources, les fichiers de modèle et leurs SHA-256 sont référencés dans le [manifeste](../installer/facial-head-manifest.json). Le venv privé réutilise la distribution CUDA de Studio en lecture. Les poids TOPOS de géométrie et le gabarit sont distribués sous MIT, l’encodeur DINOv2 et le modèle facial Google sous leurs licences respectives. Les portraits sont traités sur le PC. [TOPOS](https://github.com/ymxbj/TOPOS/blob/581ad9e218cc7559072960ea44464014c808cef3/LICENSE) · [DINOv2](https://github.com/facebookresearch/dinov2/blob/7764ea0f912e53c92e82eb78a2a1631e92725fc8/LICENSE) · [MediaPipe FaceMesh](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf)
