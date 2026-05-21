# API Catalogue Pièces — Décisions Techniques

**Statut** : Référence — à lire avant de coder `garage_parts_catalog`  
**Mis à jour** : 2026-05-21

Ce document répond aux questions ouvertes de la section 15 de `parts-catalog-integration.md`
et documente l'implémentation réelle côté API.

---

## 1. Stack technique (confirmé)

| Composant | Choix | Statut |
|---|---|---|
| Framework | **FastAPI** (Python 3.11) | ✅ Implémenté — `src/scrap_auto/api.py` |
| Serveur ASGI | **Uvicorn** (2 workers) | ✅ Prêt — démarrage via systemd |
| Driver PostgreSQL | **asyncpg** (pool async min=2, max=10) | ✅ Implémenté |
| Auth | **`X-Api-Key` header** | ✅ Implémenté (voir §3) |
| OpenAPI / Swagger | `/docs` (FastAPI built-in) | ✅ Disponible automatiquement |
| Python | 3.11 | ✅ |

---

## 2. Hébergement & URL

| Item | Valeur |
|---|---|
| Serveur | Hetzner CPX31 — même VM que Odoo 18 + PostgreSQL 16 |
| Port local | `127.0.0.1:8090` (non exposé directement) |
| Chemin Nginx | `/api/autoparts/` → proxy vers `http://127.0.0.1:8090/` |
| URL de base (prod) | `https://<domaine>/api/autoparts` |
| User système | `odoo` (même que Odoo — accès socket PostgreSQL) |

**Configuration Odoo à stocker dans `ir.config_parameter` :**

```
garage_parts_catalog.api_url  =  https://<domaine>/api/autoparts
garage_parts_catalog.api_key  =  <clé générée — voir §3>
garage_parts_catalog.enabled  =  true
garage_parts_catalog.timeout  =  15
```

---

## 3. Authentification

**Décision : `X-Api-Key` header** (question ouverte #1 — décidée)

```
X-Api-Key: <clé_secrète>
```

- Toutes les routes sauf `GET /health` exigent la clé.
- Requête sans clé ou avec clé invalide → `401 Unauthorized`.
- L'API accepte la clé si et seulement si `AUTOPARTS_API_KEY` (env var côté API) est non vide.
  Si la variable est vide au démarrage, l'auth est désactivée (dev local uniquement).
- La clé est un secret partagé — ne pas la commit dans le dépôt Odoo.

**Génération d'une clé pour l'environnement de développement :**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 4. Contrat API — État actuel vs. ce qu'il faut implémenter

> ⚠️ Le `api.py` actuel ne couvre **pas encore** tous les endpoints requis par l'intégration.
> Ce tableau indique ce qui existe et ce qu'il manque.

### 4.1 Endpoints de synchronisation (données de référence)

Ces endpoints sont **manquants** — à implémenter en priorité avant que l'équipe Odoo
commence la synchro initiale.

| Endpoint requis | Statut | Notes |
|---|---|---|
| `GET /sync/manufacturers` | ❌ À créer | Tous les fabricants d'un coup — pas de pagination nécessaire (~200 lignes) |
| `GET /sync/model-series?page=N&size=500` | ❌ À créer | Paginé — ~15 000 lignes |
| `GET /sync/car-types?page=N&size=500` | ❌ À créer | Paginé — ~100 000 lignes |
| `GET /sync/groups` | ❌ À créer | Toutes les catégories d'un coup — pas de pagination nécessaire (~500 lignes) |

**Format réponse paginée standard** (pour `model-series` et `car-types`) :

```json
{
  "data": [ ... ],
  "total": 98452,
  "page": 1,
  "pages": 197
}
```

**Format réponse liste simple** (pour `manufacturers` et `groups`) :

```json
[
  { "id": 5, "name": "FORD" },
  ...
]
```

### 4.2 Endpoints de recherche live (articles)

| Endpoint requis (intégration) | Endpoint actuel | Statut | Action requise |
|---|---|---|---|
| `GET /articles/search?car_type_id=X&group_id=Y&q=text` | `GET /search?q=&make=&model=&year=` | ⚠️ Différent | Adapter ou ajouter `/articles/search` |
| `GET /articles/{article_id}` | `GET /article/{article_id}` | ⚠️ Chemin différent | Renommer ou aliaser |

> **Différence importante** : le wizard Odoo recherche les articles par `car_type_id` (entier —
> clé primaire catalogue), alors que l'endpoint `/search` actuel filtre par `make/model/year`
> (chaînes de caractères dans `compatible_cars`). L'endpoint `/articles/search` doit accepter
> `car_type_id` comme paramètre principal.

**Signature cible de `/articles/search` :**

```
GET /articles/search
  ?car_type_id=140451     ← requis (entier, FK vers autoparts_car_types)
  &group_id=87            ← optionnel (entier, FK vers autoparts_groups)
  &q=disque+frein         ← optionnel (full-text)
  &offset=0               ← pagination (défaut 0)
  &limit=20               ← pagination (défaut 20, max 100)
```

**Réponse `/articles/search` :**

```json
{
  "total": 142,
  "offset": 0,
  "limit": 20,
  "results": [
    {
      "article_id": 12345,
      "part_name": "Disque de frein",
      "part_number": "0986479504",
      "article_manufacturer": "BOSCH",
      "group_id": 87,
      "is_oem": false,
      "thumbnail_url": "https://auto-car-parts.s3.us-east-1.amazonaws.com/..."
    }
  ]
}
```

**SQL correspondant :**

```sql
SELECT
    a.article_id, a.part_name, a.part_number, a.article_manufacturer,
    a.group_id, a.is_oem, a.thumbnail_url
FROM autoparts_articles a
JOIN autoparts_compatible_cars c USING (article_id)
WHERE c.car_type_id = $1                          -- requis
  AND ($2::int IS NULL OR a.group_id = $2)        -- group_id optionnel
  AND ($3::text IS NULL OR a.search_vector @@ websearch_to_tsquery('simple', $3))
GROUP BY a.article_id
ORDER BY a.is_oem DESC, a.article_manufacturer, a.part_name
LIMIT $4 OFFSET $5;
```

**Réponse `/articles/{article_id}` (inchangée) :**

```json
{
  "article_id": 12345,
  "article_name": "Disque de frein avant AUDI A4 B9 2.0 TDI",
  "part_number": "0986479504",
  "article_manufacturer": "BOSCH",
  "ean_numbers": ["3165143396929"],
  "oem_numbers": [{"brand": "AUDI", "number": "4F0615301D"}],
  "technical_details": [{"key": "Diamètre [mm]", "value": "320"}],
  "image_urls": ["https://auto-car-parts.s3.us-east-1.amazonaws.com/..."]
}
```

### 4.3 Endpoints existants (utilisables tel quel)

| Endpoint | Usage dans Odoo |
|---|---|
| `GET /health` | Health check systemd / monitoring |
| `GET /manufacturers` | Fallback si `/sync/manufacturers` pas encore dispo |
| `GET /models/{manufacturer_name}` | Fallback si `/sync/model-series` pas encore dispo |
| `GET /compatible/{article_id}` | Affichage liste compatibilités dans la fiche article (step 3 wizard) |

---

## 5. Réponses aux questions ouvertes (section 15 de l'intégration)

| # | Question | Décision |
|---|---|---|
| 1 | **Auth API** | ✅ `X-Api-Key` header — déjà implémenté |
| 2 | **Téléchargement image produit** | Recommandation : **désactivé par défaut** — `thumbnail_url` est une URL S3 valide, le client Odoo peut l'afficher directement sans téléchargement. Option "Importer l'image" en bouton explicite sur la fiche article. |
| 3 | **Catégorie produit des nouvelles pièces** | Recommandation : **configurable dans les paramètres** (`garage_parts_catalog.default_product_categ_id`) avec fallback sur "Pièces Auto" créée automatiquement. |
| 4 | **Type de produit créé** | ✅ `consu` (consommable) — pas de gestion de stock par défaut. |
| 5 | **Sync incrémentale** (`?updated_since=`) | **Non prévu en v1** — sync complète seulement. L'API ne trace pas les dates de modification. |
| 6 | **Gestion offline** | **Message d'erreur explicite** côté Odoo : `try/except requests.Timeout` et `HTTPError` → `raise UserError(...)`. Pas de retry automatique en v1. |
| 7 | **Langue des données** | Les données sont en **anglais** (noms de pièces/groupes tels qu'exportés depuis TecDoc). Pas de traduction côté catalogue. Les `group_name` peuvent contenir quelques mots français/allemands selon la source. |

---

## 6. Ordre d'implémentation recommandé

```
1. Implémenter GET /sync/manufacturers et GET /sync/groups    ← sans pagination, facile
2. Implémenter GET /sync/model-series et GET /sync/car-types  ← avec pagination
3. Implémenter GET /articles/search (car_type_id + group_id + q)
4. Aliaser/renommer GET /article/{id} → GET /articles/{id}
5. Déployer API (systemd + nginx)
6. Tester la synchro depuis Odoo
7. Tester le wizard end-to-end
```

---

## 7. Variables d'environnement de l'API

| Variable | Description | Exemple |
|---|---|---|
| `AUTOPARTS_DATABASE_URL` | Connexion PostgreSQL (utilisateur read-only) | `postgresql://autoparts_api:XXX@localhost/autoparts` |
| `AUTOPARTS_API_KEY` | Clé secrète partagée avec Odoo | Générer avec `secrets.token_urlsafe(32)` |

> **Note sécurité** : Le mot de passe PostgreSQL de `autoparts_api` ne doit pas contenir
> les caractères `@ $ % : /` — ils cassent le parsing de l'URL de connexion.

---

## 8. Contraintes de performance

| Endpoint | Objectif temps de réponse | Charge attendue |
|---|---|---|
| `/articles/search` | < 500 ms (p95) | < 5 req/s par garage |
| `/articles/{id}` | < 200 ms (p95) | < 2 req/s par garage |
| `/sync/car-types` (paginé) | < 5 s par page de 500 | 1 fois à l'install |
| `/health` | < 50 ms | monitoring continu |

Index PostgreSQL utilisés par les endpoints live :

```
autoparts_articles         : idx_articles_fts (GIN search_vector)
autoparts_compatible_cars  : idx_compat_car_type (car_type_id)
autoparts_articles         : idx_articles_group (group_id)
```
