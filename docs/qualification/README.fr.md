# TRELLIS Studio 3.15.1 · Qualification de la Preview Windows

[English](README.md) · Français

La Preview compilée depuis `da4d367` a passé 22 suites de régression. Elle réunit sept lots de changements depuis `f45fe3a`. Les essais ont couvert Windows avec une GeForce RTX 5070 Ti (16 Go), Ubuntu 22.04 sous WSL2, Docker Linux et Unity 6000.6.6f1. Le tableau distingue les résultats mesurés des vérifications qui demandent un autre poste, un modèle différent ou une appréciation visuelle.

## Résultats sur les personnages

**Aélis** a été générée en T-pose depuis Créer, avec High Detail GGUF, le PBR natif et la graine 42. Le calcul a duré 5 min 40 s pour 2 007 941 triangles et deux textures de 4 096 × 4 096 px. Le FBX conserve sa hauteur de 1,72 m, ses 52 os et ses clips de repos, de marche et de course. La vidéo montre trois lectures de la marche en mode Play dans Unity. Les motifs de l’armure sont plus lisibles, mais les doigts restent épais et les paumes tournent trop vers le haut. Le témoin Dense Master utilise également TOPOS. Les images comparent donc les deux parcours complets. [Visage, mains et armure](aelis-detail.png) · [Marche dans Unity](aelis-unity.mp4?raw=true) · [Cheveux avant et après réimport URP](aelis-urp.jpg)

**Elias** a été généré à 1024 avec la même graine et un atlas 2K, d’abord avec la référence en pied, puis avec un portrait complémentaire. Le portrait fait ressortir la barbe et les sourcils. Les paupières restent trop ouvertes, la coiffure présente des trous et la bouche et le contour du visage s’éloignent des repères de la référence. Cet essai justifie de garder le portrait facultatif. [Comparer les deux visages](elias-portrait.jpg)

## Suivi de l’audit

Six correctifs du socle ont été revérifiés. Les 27 autres constats concernent les dépendances Desktop (1), la qualité des personnages (2), les exports (3), le disque et les performances (4), l’interface et la VF (5), le Serveur (6) et la distribution (7).

| ID | Lot | Constat | Résultat et portée de la vérification |
|---|---|---|---|
| D1 | Socle | Disparition de tâches en attente | Vérifié. Les tâches ont survécu à la compaction de la file et au redémarrage. |
| D2 | Socle | Limites de sauvegarde et de restauration | Vérifié. Une collection exportée a été restaurée dans une bibliothèque vide. |
| D3 | Socle | Reprise après interruption | Vérifié. Le résultat précédent reste accessible et le travail peut reprendre. |
| D4 | 4 | Copies d’export abandonnées | Vérifié sur copie jetable. Le nettoyage vérifie l’original ou le ZIP avant suppression. |
| D5 | 4 | Finitions HD après restauration | Vérifié avec et sans cache. Le cache vérifié a permis de produire une nouvelle finition de 26 014 triangles. |
| S1 | 1 | Avis sur les dépendances | Partiel. Le détourage CPU isolé avec rembg 2.0.88 reproduit le masque alpha initial. Des avis restent ouverts sur PyTorch et Transformers. |
| S2 | Socle | Secrets de double authentification | Vérifié. Enrôlement, migration et connexion après restauration avec une clé sauvegardée séparément. |
| S3 | 6 | Ressources des convertisseurs | Vérifié localement. L’annulation libère le quota et le GLB suivant aboutit. Deux comptes restent isolés via REST et MCP. |
| S4 | 6 | Droits et échéance des clés API | Vérifié localement. Lecture seule, expiration, révocation et délai de migration des clés existantes ont été testés. |
| S5 | 7 | Installation hors ligne et intégrité | Partiel. Le support altéré a été refusé. L’Atelier, MCP et les animations standard ont été installés hors ligne sur le Windows existant. Windows vierge et signature restent à vérifier. |
| S6 | 3 | Provenance des matériaux et des moteurs | Vérifié sur PBR natif, UltraTex 2K à six vues et repli multivue. Le moteur utilisé est indiqué comme inconnu si l’ancien modèle ne conserve que la préférence demandée. |
| G1 | 2 | Doigts ou membres coupés | Vérifié localement. Les alertes examinent le masque d’origine avant le recadrage. |
| G2 | 2 | Ressemblance du visage | Partiel. Sur trois références, le visage occupait environ 39 × 52–53 px à la première passe native. Voir Elias ci-dessus. Les visages stylisés restent à examiner. |
| G3 | 2 | Intersections des vêtements | Vérifié sur huit témoins. Les quatre paires qui se croisent et les quatre paires espacées ont été reconnues. Les contacts voulus autour des yeux et les vêtements superposés demandent un examen visuel. |
| G4 | 2 | Profondeur des genoux et des chevilles | Vérifié au repos sur Aélis et RIFT. Les profils Simple et Expressif à mains rigides conservent les quatre centres articulaires dans le maillage après réimport. |
| G5 | Socle | Appui de la paume après édition d’un franchissement | Vérifié après modification des durées et des coupes du clip. Écart maximal de la paume sur le témoin Unity de 14,85 mm. |
| G6 | 2 | Diagnostic des déformations selon le clip | Partiel. Quatre personnages ont été échantillonnés à 240 Hz. Sur Aélis, le pire écart de la peau de la paume atteint 17,31 mm à 1,604 s. |
| U1 | Socle | Réimport de terrain Unity | Vérifié. L’import d’un autre terrain préserve la sculpture et la peinture locales. |
| U2 | 3 | Matériaux et cheveux en URP | Partiel. Les silhouettes mates de la coiffure coïncident à 99,60 % de face et 99,74 % de trois quarts. Les cheveux opaques sont plus sombres en URP. Une coiffure à mèches transparentes reste à tester. |
| U3 | 3 | Os des niveaux de détail | Vérifié sur témoins. La correspondance utilise la hiérarchie et la pose de liaison. Les os ambigus ou absents ont été refusés. Deux niveaux de détail ont été rendus en URP. |
| U4 | 3 | FBX livré et réimporté en moteur | Partiel. Sur trois poses Unity, l’écart avec le GLB atteint au maximum 0,38 mm pour sept articulations. Unreal et d’autres versions de Unity restent à valider. |
| U5 | 3 | Précision de peinture et d’impression | Vérifié sur étalons. Les parois mesurent 2,000 et 4,000 mm. Studio indique la résolution de peinture du terrain. |
| E1 | 4 | Ouverture d’une grande collection | Partiel. À 5 000 fiches synthétiques, deux onglets Edge ont affiché leurs premières cartes en 24,0 et 26,7 s. L’ouverture à froid reste lente. |
| E2 | 4 | Mémoire des maillages denses | Vérifié sur Aélis. Pour des bornes identiques, le pic mémoire du processus passe de 879,1 à 261,6 Mio. |
| E3 | 4 | Processus et profils d’aperçu orphelins | Vérifié localement. Vingt rendus Edge, annulation, délai dépassé, arrêt et nettoyage de profils orphelins ont été testés. |
| E4 | 4 | Téléchargements partiels et attente WSL | Vérifié sur fichier partiel, empreinte incorrecte, réponse HTTP 416 et client WSL bloqué simulé. |
| E5 | 6 | Charge de plusieurs espaces | Partiel. À 50 espaces vides sur Windows, le 95e centile de lecture de la liste est de 3,97 ms. Une charge sur des bibliothèques remplies et actives reste à tester. |
| E6 | 7 | Identification du build installé | Partiel. La version amont et le commit du fork sont identifiés séparément. Le contrôle sur un Windows vierge reste à réaliser. |
| E7 | 7 | Contrôles de diffusion | Partiel. Les tests rapides et le workflow matériel sur tag sont configurés. L’exécution CI distante et la matrice complète des moteurs restent à valider. |
| I1 | 5 | Textes d’interface non traduits | Vérifié en français et en anglais sur les parcours et messages dynamiques testés à 200 % de zoom. |
| I2 | 5 | Clavier et lecteur d’écran | Partiel. Nom des dialogues, commandes 3D et restitution du focus sont vérifiés dans Edge. L’écoute avec NVDA reste à valider. |
| I3 | 5 | Réglages selon le point d’entrée | Vérifié. À image et graine 84 identiques, les réglages du visage avec Pixal3D correspondent dans les recettes de Créer, de la File et de l’API REST. |
| I4 | 3 | Verdicts STL des exports par lot | Vérifié sur ZIP mixte. Le STL sain et celui à réparer conservent chacun leur verdict et leur empreinte. |

## Distribution et retour arrière

La Preview Windows qualifiée est non signée. L’exécutable mesure 19 569 805 octets et son SHA-256 est `b3bbdedb58be8ac8481d1a97409404eb64dee471d7747bd7a8dadd3d08979e2f`. Les 1 518 fichiers extraits correspondent au manifeste du paquet. L’essai hors ligne couvre l’Atelier, MCP et les bibliothèques standard d’animation sur un Windows existant. Les moteurs GPU et WSL s’installent séparément. [Installation Windows](../WINDOWS_SETUP.md) · [High Detail natif](../NATIVE_PROFILES.md#windows-setup) · [Avis de sécurité et mesures appliquées](../../SECURITY.md)

Dans une copie de travail jetable, l’annulation de chaque lot a reproduit exactement l’arbre Git du lot précédent jusqu’à `f45fe3a`. Chaque version a relu les archives de collection de l’autre. Deux restaurations indépendantes du Serveur sur le même PC Windows ont conservé l’isolation des comptes, les empreintes des modèles, la double authentification TOTP et les quotas. La restauration sur un autre hôte et la signature d’une diffusion avec le certificat du mainteneur restent à valider. [Sauvegarde et restauration du Serveur](../SERVER.md)
