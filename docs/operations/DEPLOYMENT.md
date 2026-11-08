# Déploiement pilote et exploitation

Ce guide décrit la mise en service du pilote sur **un serveur unique**, sa mise à jour, son retour arrière, ses sauvegardes et sa surveillance.

Fichiers concernés :
- `deploy/compose.pilot.yml` : la pile ;
- `deploy/Caddyfile` : le proxy ;
- `deploy/.env.example` : la configuration ;
- `scripts/backup_db.sh` et `scripts/restore_db.sh` : sauvegarde et restauration.

## 1. Architecture

```
Internet ──443/80──▶ proxy (Caddy : TLS automatique, client Web, en-têtes de sécurité)
                        │ /api/*  /admin/*  /static/*
                        ▼
                     api (Django + gunicorn, 3 workers) ──▶ db (PostgreSQL 17)
                        │
                        └── volume « files » (fiches techniques, justificatifs, photos)
migrate : tâche ponctuelle, exécutée avant chaque démarrage de l'API
backup / restore : tâches d'exploitation (profil « ops »)
```

- Seul le proxy est exposé. La base de données et l'API restent sur le réseau Docker interne.
- Le certificat HTTPS est obtenu et renouvelé automatiquement (Let's Encrypt) pour `FMS_DOMAIN`.
- Le client Web est servi avec une politique de sécurité de contenu stricte : rien n'est chargé depuis une autre origine. Les fichiers `index.html` et `sw.js` sont toujours revalidés, ce qui permet à une nouvelle version d'atteindre les appareils. Les fichiers versionnés de `assets/` sont mis en cache un an.
- Les fichiers statiques de l'admin Django sont servis par l'API (WhiteNoise), compressés et versionnés.
- Le jeton de rafraîchissement du client Web est dans un cookie `HttpOnly`, `Secure` et `SameSite=Strict` (Q26). L'application mobile garde le sien dans le trousseau du système.

## 2. Prérequis

| Élément | Minimum conseillé pour le pilote |
|---|---|
| Serveur | Linux x86-64, 2 vCPU, 4 Go de RAM, 40 Go de disque (base + fichiers + 30 jours de sauvegardes) |
| Logiciels | Docker Engine 27 ou plus récent, avec le plugin Compose v2 |
| Réseau | Ports 80 et 443 ouverts en entrée ; enregistrement DNS A/AAAA de `FMS_DOMAIN` vers le serveur |
| Sauvegarde externe | Un emplacement hors du serveur (autre machine, stockage objet) pour copier `BACKUP_HOST_DIR` |

## 3. Première installation

```bash
git clone <dépôt> /srv/fms/app && cd /srv/fms/app
git checkout <tag de la version>          # par exemple v0.12.0
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
# Renseigner FMS_DOMAIN, FMS_ACME_EMAIL, DJANGO_SECRET_KEY, POSTGRES_PASSWORD, BACKUP_HOST_DIR,
# FMS_VERSION=<tag>. Générer chaque secret avec :
python3 -c "import secrets; print(secrets.token_urlsafe(50))"

mkdir -p /srv/fms/backups
docker compose -f deploy/compose.pilot.yml --env-file deploy/.env up -d --build
docker compose -f deploy/compose.pilot.yml --env-file deploy/.env ps     # api : healthy
curl -fsS https://$FMS_DOMAIN/api/v1/health/                             # {"status":"ok",...}

# Compte du personnel de la plateforme (accès à /admin/)
docker compose -f deploy/compose.pilot.yml --env-file deploy/.env exec api \
  python manage.py createsuperuser
```

La première organisation et son administrateur se créent depuis l'admin (`/admin/` → Organisations → Ajouter) ou par l'API. Les invitations sont envoyées depuis la même page : le jeton n'est affiché qu'une seule fois.

## 4. Mise à jour

```bash
cd /srv/fms/app
docker compose -f deploy/compose.pilot.yml --env-file deploy/.env run --rm backup   # sauvegarde avant
git fetch --tags && git checkout <nouveau tag>
sed -i 's/^FMS_VERSION=.*/FMS_VERSION=<nouveau tag>/' deploy/.env
docker compose -f deploy/compose.pilot.yml --env-file deploy/.env up -d --build
```

- Les migrations s'appliquent automatiquement : `migrate` s'exécute avant que `api` redémarre. Si elles échouent, l'API ne démarre pas et la version précédente n'est pas remplacée.
- Les appareils hors ligne gardent leur file d'attente. Ils l'envoient à la version suivante : le protocole de synchronisation est versionné.
- Après la mise à jour, contrôler `ps`, `/api/v1/health/`, la connexion Web et l'admin.

## 5. Retour arrière

Chaque image est étiquetée avec `FMS_VERSION` : l'ancienne version reste disponible localement.

1. **Sans migration de schéma entre les deux versions** : remettre l'ancien `FMS_VERSION` dans `deploy/.env`, revenir au tag précédent (`git checkout`), puis `up -d`.
2. **Avec migration** : restaurer la sauvegarde faite juste avant la mise à jour (§6.3), puis redémarrer l'ancienne version. Les saisies faites entre la mise à jour et le retour arrière sont perdues côté serveur. Les appareils qui les ont envoyées les considèrent comme synchronisées. Il faut donc les ressaisir : à éviter, en testant chaque mise à jour sur une copie (§8).

## 6. Sauvegardes

### 6.1 Contenu

`backup` écrit dans `BACKUP_HOST_DIR` :
- `fms-<date>.dump` : la base PostgreSQL au format personnalisé, compressée. Le script vérifie que le fichier est lisible (`pg_restore --list`) ;
- `fms-files-<date>.tar.gz` : les fichiers stockés (fiches techniques, justificatifs, photos).

Les sauvegardes de plus de `BACKUP_RETENTION_DAYS` jours (30 par défaut) sont supprimées.

### 6.2 Planification (cron de l'hôte)

```cron
# Tous les jours à 02:30 ; puis copie hors du serveur.
30 2 * * * cd /srv/fms/app && docker compose -f deploy/compose.pilot.yml --env-file deploy/.env run --rm backup >> /var/log/fms-backup.log 2>&1
15 3 * * * rsync -a --delete /srv/fms/backups/ sauvegarde@autre-machine:/sauvegardes/fms/
```

Une sauvegarde restée sur le même disque que la base ne protège pas d'une panne de ce disque : la copie externe est obligatoire.

### 6.3 Restauration

```bash
cd /srv/fms/app
docker compose -f deploy/compose.pilot.yml --env-file deploy/.env stop api proxy
docker compose -f deploy/compose.pilot.yml --env-file deploy/.env run --rm restore \
  /backups/fms-<date>.dump /backups/fms-files-<date>.tar.gz
docker compose -f deploy/compose.pilot.yml --env-file deploy/.env up -d
```

La base est restaurée en une seule transaction : un échec la laisse dans son état antérieur. Les fichiers du volume `files` sont remplacés par ceux de l'archive.

### 6.4 Test de restauration (mensuel)

Une sauvegarde jamais restaurée n'est pas une sauvegarde. Chaque mois :
1. restaurer la dernière sauvegarde sur une machine de test, avec la même pile et un autre `FMS_DOMAIN` ;
2. contrôler `/api/v1/health/` et la connexion, compter les organisations, les transactions et les fichiers ;
3. consigner la date et le résultat.

Le scénario « sauvegarde, modification, restauration » a été exécuté sur la pile locale le 8 novembre 2026. L'organisation créée après la sauvegarde a bien disparu, et l'API répondait de nouveau normalement.

## 7. Surveillance

| Contrôle | Commande ou point d'accès | Attendu |
|---|---|---|
| Santé de l'API et de la base | `GET https://$FMS_DOMAIN/api/v1/health/` | `200`, `{"status": "ok", "database": "ok"}` ; `503` si la base est inaccessible |
| Conteneurs | `docker compose ... ps` | `api` à l'état `healthy`, `migrate` terminé avec le code 0 |
| Journaux | `docker compose ... logs -f api proxy` | Accès au format JSON (proxy) ; chaque requête de l'API porte un identifiant (`X-Request-ID`) |
| Espace disque | `df -h /var/lib/docker /srv/fms/backups` | Moins de 80 % utilisés |
| Sauvegarde du jour | `ls -l /srv/fms/backups` | Un `.dump` et un `.tar.gz` datés du jour |
| Coût de l'IA | Admin → Journaux d'appels IA | Sous le quota mensuel (`FMS_AI_MONTHLY_REQUEST_LIMIT`) |
| Conflits de synchronisation | Admin → Conflits (statut « ouvert ») | Traités régulièrement : ils attendent une décision humaine |

Une sonde externe (service de supervision) devrait interroger `/api/v1/health/` toutes les minutes et alerter après trois échecs.

## 8. Sécurité

- `deploy/.env` contient tous les secrets : droits `600`, jamais dans le dépôt (le fichier est ignoré par git).
- **Rotation des clés** (en cas de fuite) :
  - `DJANGO_SECRET_KEY` invalide les sessions de l'admin ;
  - `JWT_SIGNING_KEY` (facultative, égale par défaut à `DJANGO_SECRET_KEY`) invalide les jetons de tous les utilisateurs Web et mobiles, qui doivent se reconnecter. Les saisies hors ligne en attente restent sur les appareils et partent après la reconnexion.

  Définir `JWT_SIGNING_KEY` séparément permet de renouveler l'une des deux clés sans toucher à l'autre.
- **Révocation d'un appareil perdu** : Admin → Appareils → « Révoquer ». Ses jetons sont refusés immédiatement.
- **Comptes du personnel** : un compte nominatif par personne, aucun compte partagé. Le droit `is_staff` donne accès aux données de toutes les organisations (Q34) : à réserver strictement au support.
- Tester chaque mise à jour sur une copie restaurée avant de l'appliquer au pilote (§6.4).
- Les ports de la base et de l'API ne sont jamais publiés sur l'hôte. Ne pas ajouter de section `ports` à `db` ou `api`.

## 9. Limites connues du pilote

- Serveur unique, sans haute disponibilité. Une panne de la machine interrompt le service jusqu'à sa restauration (perte maximale : depuis la dernière sauvegarde, soit 24 h). Les appareils continuent de fonctionner hors ligne pendant ce temps.
- Les appels à l'IA sont synchrones, dans la requête (Q24). Le délai du proxy est de 130 s.
- La RLS PostgreSQL n'est pas activée (Q27) : l'isolation est appliquée par l'application et vérifiée par la suite de tests d'isolation.
- Fichiers stockés sur un volume local. Un stockage objet compatible S3 est possible, mais n'est pas configuré.
- Les sauvegardes ne sont pas chiffrées à l'écriture : la copie externe doit l'être (par exemple un dépôt chiffré ou un chiffrement côté stockage). Elles contiennent des données financières et personnelles.
