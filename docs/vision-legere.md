# Vision légère : détection et reconnaissance sur le Raspberry Pi

Ce document explique comment la caméra repère les personnes (« silhouettes ») et reconnaît les
visages connus, et pourquoi cette partie a été réécrite pour tourner sur le Raspberry Pi.

## Le problème de départ

La première version utilisait deux grosses bibliothèques d'intelligence artificielle :

- **PyTorch** (via `ultralytics`) pour YOLO, qui trouve les personnes ;
- **TensorFlow** (via `DeepFace`) pour reconnaître les visages.

Ça marchait sur un PC, mais c'était beaucoup trop lourd pour un Raspberry Pi :

| | Version lourde |
|---|---|
| Image Docker de l'API | **17,3 Go** |
| Mémoire de l'API | **~2,4 Go** |
| Démarrage de l'API | ~1 minute (chargement des modèles et téléchargements) |
| Une analyse (sur un PC) | ~300 ms |

Sur le Pi, ça voulait dire : un build interminable, une carte SD remplie, un processeur saturé, et
donc une vidéo qui saccade.

## L'idée : garder les mêmes modèles, changer le moteur

Un **modèle** (YOLO, le reconnaisseur de visages…) n'est qu'un fichier de « poids ». PyTorch et
TensorFlow sont des **moteurs** pour exécuter ces fichiers, mais ce sont aussi des outils complets
pour *entraîner* des modèles, d'où leur poids énorme. Nous, on ne fait qu'*utiliser* des modèles
déjà entraînés.

On convertit donc les modèles au format **ONNX**, un format standard que **OpenCV** sait exécuter
tout seul. OpenCV était déjà installé pour lire les images : plus besoin de PyTorch ni de
TensorFlow dans l'application.

Bonus : un fichier ONNX est le même sur un PC (processeur x86) et sur le Pi (processeur ARM).

## Les trois modèles

| Modèle | Rôle | Taille |
|---|---|---|
| **YOLOv8n** | trouver les personnes dans l'image | 12 Mo |
| **YuNet** | trouver le visage d'une personne et repérer ses yeux | 0,2 Mo |
| **SFace** | transformer un visage en « empreinte » (128 nombres) | 37 Mo |

**Comment marche la reconnaissance :** chaque photo de `backend/data/known_faces/` est transformée
en empreinte au démarrage. Quand la caméra voit un visage, on calcule son empreinte et on la compare
à celles des photos. Deux photos de la même personne donnent des empreintes proches ; si aucune
n'est assez proche, la personne est un « INTRUS ».

## Les quatre astuces qui allègent la charge

### 1. Des images plus petites
YOLO analyse l'image en **320 pixels** au lieu de 640 : c'est environ **4 fois moins de calcul**,
et ça suffit largement pour repérer quelqu'un dans une pièce.

### 2. Ne rien analyser quand rien ne bouge
Avant chaque analyse, on compare l'image avec la précédente, réduite à une vignette de 64×48 pixels
en noir et blanc. Cette comparaison ne coûte presque rien. Si rien n'a bougé, on renvoie le
résultat précédent **sans lancer aucun modèle**. Par sécurité, on refait quand même une vraie
analyse toutes les 5 secondes.

### 3. Suivre les personnes au lieu de les reconnaître à chaque fois
Entre deux analyses, une personne bouge un peu : son nouveau cadre recouvre l'ancien. Le
**suivi** (`tracker.py`) relie donc chaque cadre à la personne de l'analyse précédente.
Conséquence : on reconnaît le visage **une seule fois** quand la personne apparaît, puis elle garde
son nom tant qu'on la suit, même si elle se retourne. On revérifie seulement :
- toutes les **1 s** pour une personne pas encore reconnue ;
- toutes les **10 s** pour une personne reconnue (au cas où deux personnes se seraient croisées).

### 4. Ne pas prendre tout le processeur
Les modèles n'ont le droit d'utiliser que **2 cœurs** (`VISION_THREADS=2`) : il en reste pour la
vidéo, l'API et la base de données.

## Les modèles sont préparés automatiquement au build

Pas de commande à lancer à la main, ni sur le PC ni sur le Pi : pendant le
`docker compose build` (ou `make deploy`), l'étape `models` du `backend/Dockerfile` :

1. copie **YOLOv8n déjà converti en ONNX**, rangé dans le dépôt (`backend/models/yolov8n.onnx`,
   12 Mo) ;
2. télécharge YuNet et SFace depuis le dépôt officiel d'OpenCV, en vérifiant leur empreinte
   (`--checksum`), pour être sûr d'avoir les bons fichiers.

L'image finale contient les 3 fichiers `.onnx` dans `/app/models`. Grâce au cache de Docker, les
téléchargements ne se refont que si on modifie ces lignes.

**Pourquoi YOLO est déjà converti dans le dépôt :** la conversion en ONNX a besoin de PyTorch
(plus d'1 Go une fois installé). Au premier essai, on la faisait pendant le build, et le Raspberry
Pi a manqué de place sur sa carte SD. La conversion se fait donc une fois pour toutes, sur un PC,
avec `scripts/export-yolo-onnx.sh` (dans un conteneur jetable). On ne la refait que pour changer
de modèle ou de taille d'image, puis on commite le nouveau fichier.

## Résultat

Mesuré sur un PC, avec la caméra du Raspberry et les photos de l'équipe :

| | Version lourde | Version légère |
|---|---|---|
| Image Docker de l'API | 17,3 Go | **837 Mo** |
| Mémoire de l'API | ~2,4 Go | **~400 Mo** |
| Démarrage de l'API | ~1 minute | **quelques secondes** |
| Une analyse (YOLO + visage) | ~300 ms | **~37 ms** |
| CPU de l'API, caméra en marche | 17 à 85 % | **~1 à 2 %** |
| Photos reconnues (test sur nos 10 photos) | 4 sur 10 | **4 sur 10** |
| Fausses reconnaissances | 0 | **0** |

La qualité de reconnaissance est la même. Les photos non reconnues sont celles de profil :
voir « Bien choisir les photos » plus bas.

Sur le Raspberry Pi, une analyse sera plus lente que sur un PC (compter quelques dizaines à une
centaine de millisecondes sur un Pi 5, environ 2 à 3 fois plus sur un Pi 4), ce qui laisse
largement de la marge avec une analyse par seconde.

## Mettre en route sur le Raspberry Pi

1. Dans `backend/.env` du Pi :
   ```
   CAMERA_STREAM_URL=http://webcam:8080/stream
   VISION_ENABLED=true
   VISION_IDENTIFY_FACES=true
   ```
2. Déployer : `make deploy`. Le premier build prépare les modèles (quelques minutes), les suivants
   réutilisent le cache.
3. Vérifier dans les logs que les photos sont chargées :
   ```sh
   docker compose logs api | grep -iE "known face|skipping|vision"
   ```
4. Surveiller la température du Pi sur le tableau de bord. Si le processeur chauffe trop, on peut
   espacer les analyses (`VISION_INTERVAL_SECONDS=2`) ou ne garder que les silhouettes
   (`VISION_IDENTIFY_FACES=false`).

## Bien choisir les photos

Les photos de `backend/data/known_faces/` font toute la qualité de la reconnaissance :

- **2 ou 3 photos de face** par personne : les photos de profil sont ignorées au démarrage, car
  elles provoquent des confusions entre les gens ;
- l'idéal : des photos **prises avec la caméra elle-même**, à la distance où les gens passent ;
- les noms : `kevan1.jpg`, `kevan2.jpg` → la personne s'appelle « kevan ».

Après un ajout ou un changement de photo, redémarrer l'API : `docker compose restart api`.

## Où est le code

| Fichier (`backend/src/app/infrastructure/vision/`) | Rôle |
|---|---|
| `person_detector.py` | YOLO : trouver les personnes |
| `face_whitelist.py` | YuNet + SFace : empreintes des visages, comparaison avec les photos |
| `tracker.py` | suivre chaque personne d'une analyse à l'autre |
| `motion.py` | sauter l'analyse quand rien ne bouge |
| `light_analyzer.py` | enchaîner le tout pour chaque image |
| `detection_worker.py` | lire le flux vidéo et envoyer les résultats au navigateur |

Les réglages fins (seuils, délais) sont des constantes en haut de chaque fichier, avec un
commentaire qui explique leur valeur.
