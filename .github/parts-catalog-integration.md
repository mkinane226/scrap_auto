# PLAN — Intégration Catalogue Pièces Auto (Third-Party API)

**Statut** : Planification — v2 (mise à jour : car_types pré-chargés, form véhicule enrichi, spec API à implémenter)  
**Module cible** : `garage_parts_catalog` (nouveau module, dépend de `repair_auto`)  
**Priorité** : P1 — Fonctionnalité cœur de métier

---

## 1. Vision & Périmètre

### Ce que fait cette fonctionnalité

Depuis l'onglet **Pièces** d'un ordre de réparation, l'utilisateur peut lancer une recherche dans un catalogue externe de pièces automobiles (millions de références). Il sélectionne le véhicule (marque → modèle → motorisation), filtre par catégorie de pièce, consulte les fiches articles (photos, OEM, EAN, specs techniques, compatibilités) et ajoute la pièce choisie directement sur l'ordre de réparation. Si le produit n'existe pas encore dans Odoo, il est créé automatiquement.

### Ce que ce plan ne couvre PAS

- La gestion des prix (le catalogue n'a pas de prix — la tarification reste manuelle)
- La commande fournisseur automatique depuis le catalogue
- La synchronisation complète du catalogue dans Odoo (trop volumineux)

---

## 2. Structure de la Base de Données Catalogue (API Source)

### Tables de référence (données statiques — toutes pré-chargées en base Odoo)

```
manufacturers
  manufacturer_id  PK
  manufacturer_name

model_series
  model_series_id  PK
  manufacturer_id  FK → manufacturers
  display_name          "FIAT 500 (111_, 101_, 110_)"
  model_native_name     "500 (111_, 101_, 110_)"
  year_from
  year_to

car_types  (motorisations — PRÉ-CHARGÉES intégralement)
  car_type_id      PK
  model_series_id  FK
  manufacturer_id  (dénormalisé)
  type_label            "4.8 V8"
  engine_code
  cylinder / capacity / fuel_type / power
  year_from / year_to
  car_type_title        "MORGAN - AERO Coupé - 4.8 V8"
  details               JSON array [{key, value}, ...]

groups  (catégories hiérarchiques à 3 niveaux)
  group_id         PK
  group_name            chemin complet "Échappement > Pièces de montage > Support"
  primary_group_name    "Échappement"
  subcategory_name      "Pièces de montage"
  sub_subcategory_name  "Support"
```

> ✅ **Décision architecturale** : Les `car_types` (~100k lignes) sont pré-chargés dans Odoo au même titre que les fabricants et les séries. Cela élimine toute latence API lors de la sélection de la motorisation d'un véhicule, et permet de lier la fiche véhicule directement à un `catalog.car.type` via Many2one.

### Table récupérée uniquement à la demande (live)

```
articles  (résultats de recherche — millions de lignes, jamais cachés)
  article_id       PK
  part_name
  part_number      numéro article fournisseur
  article_number
  article_manufacturer   ex. "BOSCH"
  supplier_id
  is_oem           boolean
  thumbnail_url         S3 URL — image miniature (affichée dans les résultats)
  manufacturer_id / model_series_id / car_type_id
  group_id         FK → groups
  [details_url]         ← artefact de scraping — IGNORÉ par l'API
  [search_vector]       ← ts_vector interne PostgreSQL — utilisé côté API pour le FTS, non exposé

article_details  (fiche complète — récupérée par article_id)
  article_id
  article_name          nom complet avec contexte véhicule
  ean_numbers           JSON array de strings
  oem_numbers           JSON array [{brand, number}, ...]
  technical_details     JSON array [{key, value}, ...]
  image_urls            JSON array de S3 URLs — toutes les photos de l'article
```

> **Notes importantes** :
> - `details_url` : URL de la page web qui a été scrapée pour obtenir les données. Elle ne doit pas figurer dans les réponses de l'API ni être stockée côté Odoo.
> - `search_vector` : colonne `tsvector` PostgreSQL utilisée en interne pour la recherche full-text côté API (`WHERE search_vector @@ plainto_tsquery(...)`). Non exposée dans les réponses JSON.
> - Seules les **S3 URLs** (`thumbnail_url` et `image_urls`) sont des URLs externes pertinentes — elles sont directement affichées dans le navigateur du client Odoo sans proxification.

---

## 3. Architecture du Nouveau Module

### Nom & emplacement

```
my-addons/repair_auto/             ← NE PAS modifier (module existant)
my-addons/garage_parts_catalog/    ← NOUVEAU MODULE
  __manifest__.py
  __init__.py
  models/
    __init__.py
    catalog_manufacturer.py        # cache local des fabricants
    catalog_model_series.py        # cache local des séries
    catalog_car_type.py            # cache local des motorisations (~100k lignes)
    catalog_group.py               # cache local des catégories
    catalog_api.py                 # couche d'accès API (service)
    repair_order.py                # héritage repair.order (bouton catalogue)
    garage_vehicle.py              # héritage garage.vehicle (liaison car_type)
    product_template.py            # héritage product.template (catalog_article_id)
    res_config_settings.py         # paramètres API
  wizard/
    __init__.py
    wizard_parts_search.py         # wizard transient + logique de recherche
  views/
    catalog_manufacturer_views.xml
    catalog_car_type_views.xml     # liste motorisations (lecture seule)
    catalog_group_views.xml
    repair_order_views.xml         # ajout du bouton "Catalogue"
    garage_vehicle_views.xml       # enrichissement form véhicule (sélection catalogue)
    wizard_parts_search_views.xml  # formulaire du wizard (étapes)
    res_config_settings_views.xml
    menu_views.xml
  security/
    catalog_security.xml
    ir.model.access.csv
  data/
    catalog_sync_actions.xml       # ir.actions.server pour la synchro initiale
  static/src/
    js/
      parts_catalog_wizard.js      # Composant OWL du wizard multi-étapes
      catalog_article_card.js      # Composant OWL carte article
    xml/
      parts_catalog_wizard.xml
      catalog_article_card.xml
    css/
      parts_catalog.css
```

### Dépendances déclarées

```python
'depends': ['repair_auto', 'repair', 'product', 'mail']
```

---

## 4. Modèles Odoo Nouveaux

### 4.1 `catalog.manufacturer` — Cache fabricants catalogue

| Champ | Type | Notes |
|---|---|---|
| `external_id` | Integer | `manufacturer_id` dans le catalogue (unique) |
| `name` | Char | Nom fabricant |
| `vehicle_brand_ids` | Many2many(`garage.vehicle.brand`) | Lien avec les marques locales du garage |

> **Rôle du lien `vehicle_brand_ids`** : permet le pré-remplissage du wizard quand la marque du véhicule de l'OR est connue.

### 4.2 `catalog.model.series` — Cache séries modèles

| Champ | Type | Notes |
|---|---|---|
| `external_id` | Integer | `model_series_id` |
| `manufacturer_id` | Many2one(`catalog.manufacturer`) | |
| `display_name` | Char | |
| `year_from` | Date | |
| `year_to` | Date | |

### 4.3 `catalog.group` — Cache catégories pièces

| Champ | Type | Notes |
|---|---|---|
| `external_id` | Integer | `group_id` |
| `group_name` | Char | Chemin complet |
| `primary_group_name` | Char | Catégorie principale |
| `subcategory_name` | Char | Sous-catégorie |
| `sub_subcategory_name` | Char | Sous-sous-catégorie |

### 4.4 `catalog.car.type` — Cache motorisations

| Champ | Type | Notes |
|---|---|---|
| `external_id` | Integer | `car_type_id` catalogue (unique, index obligatoire) |
| `model_series_id` | Many2one(`catalog.model.series`) | Série parente |
| `manufacturer_id` | Many2one(`catalog.manufacturer`) | Dénormalisé pour perf. des filtres |
| `type_label` | Char | Ex. "2.0 TDI 150 CV" |
| `engine_code` | Char | Code moteur |
| `cylinder` | Integer | Nombre de cylindres |
| `capacity` | Integer | Cylindrée en cm³ |
| `fuel_type` | Char | Ex. "Diesel", "Essence", "Hybride" |
| `power` | Integer | Puissance en CV |
| `year_from` | Integer | Année de début |
| `year_to` | Integer | Année de fin (0 = actuel) |
| `car_type_title` | Char | Titre complet ex. "AUDI - A4 (B9) - 2.0 TDI 150 CV" |
| `details_json` | Text | JSON [{key, value}] — specs techniques |

> **Note performance** : Avec ~100k enregistrements, un index sur `(model_series_id, manufacturer_id)` est obligatoire. La recherche dans le wizard utilise le domaine Odoo standard — pas de recherche full-text nécessaire à ce niveau.

### 4.5 Héritages sur modèles existants

#### `garage.vehicle` — liaison directe au catalogue

| Champ | Type | Notes |
|---|---|---|
| `catalog_manufacturer_id` | Many2one(`catalog.manufacturer`) | Fabricant catalogue |
| `catalog_model_series_id` | Many2one(`catalog.model.series`) | Série catalogue (filtrée par fabricant) |
| `catalog_car_type_id` | Many2one(`catalog.car.type`) | **Motorisation exacte** (filtrée par série) |

> Ces 3 champs remplacent l'ancien `catalog_car_type_id` (Integer) + `catalog_car_type_label` (Char). Le Many2one permet le domain filtering en cascade et le pré-remplissage fiable du wizard.

> **Onchange en cascade** :
> - `_onchange_catalog_manufacturer_id` → vide `catalog_model_series_id` et `catalog_car_type_id`
> - `_onchange_catalog_model_series_id` → vide `catalog_car_type_id`
> - `_onchange_brand_id` → si la marque a un fabricant catalogue lié, pré-remplit `catalog_manufacturer_id`

#### `product.template` — traçabilité catalogue

| Champ | Type | Notes |
|---|---|---|
| `catalog_article_id` | Integer | `article_id` dans le catalogue (unique, index) |
| `catalog_part_number` | Char | Référence article fabricant |
| `catalog_manufacturer_name` | Char | Nom fabricant catalogue |

> Ces champs servent à détecter si un article catalogue a déjà été importé comme produit Odoo.

#### `repair.order` — bouton d'accès au catalogue

Ajout d'un bouton **"🔍 Catalogue pièces"** dans l'onglet Pièces qui ouvre le wizard. Pas de nouveau champ stocké sur l'OR.

---

## 5. Spec API à Implémenter (l'API est créée pour servir Odoo)

> ⚠️ **Contexte** : L'API REST n'existe pas encore. Elle sera développée spécifiquement pour ce module. Cette section définit ce que l'API DOIT exposer. Le développeur de l'API implémente ces endpoints.

### Architecture cible

```
[Odoo garage_parts_catalog]
        │
        │  HTTP REST (JSON)
        │  Bearer Token ou X-Api-Key header
        ▼
[API auto-parts  — à créer]
        │
        ▼
[PostgreSQL catalogue  — existant]
  manufacturers / model_series / car_types / groups / articles / article_details
```

### Configuration Odoo (stockée dans `ir.config_parameter`)

| Clé système | Description |
|---|---|
| `garage_parts_catalog.api_url` | URL de base ex. `https://api.i2doo.ma/catalog/v1` |
| `garage_parts_catalog.api_key` | Clé d'API (secret — jamais affiché en clair dans les vues) |
| `garage_parts_catalog.enabled` | `true`/`false` |
| `garage_parts_catalog.timeout` | Timeout en secondes (défaut: 15) |

### Endpoints requis — Synchronisation (données de référence)

Ces endpoints sont appelés **une seule fois** à l'installation et lors des mises à jour manuelles. Ils doivent supporter la **pagination** pour les volumes importants.

| Méthode | Endpoint | Paramètres | Réponse |
|---|---|---|---|
| `GET` | `/sync/manufacturers` | — | `[{id, name}]` — tous les fabricants |
| `GET` | `/sync/model-series` | `?page=N&size=500` | `[{id, manufacturer_id, display_name, year_from, year_to}]` |
| `GET` | `/sync/car-types` | `?page=N&size=500` | `[{id, model_series_id, manufacturer_id, type_label, engine_code, cylinder, capacity, fuel_type, power, year_from, year_to, car_type_title}]` |
| `GET` | `/sync/groups` | — | `[{id, group_name, primary_group_name, subcategory_name, sub_subcategory_name}]` |

> Réponse paginée standard : `{data: [...], total: N, page: N, pages: N}`

### Endpoints requis — Recherche live (articles)

Ces endpoints sont appelés **en temps réel** depuis le wizard. Ils doivent répondre en < 2 secondes.

| Méthode | Endpoint | Paramètres obligatoires | Paramètres optionnels |
|---|---|---|---|
| `GET` | `/articles/search` | `car_type_id` | `group_id`, `q` (texte libre), `offset`, `limit` (défaut 20) |
| `GET` | `/articles/{article_id}` | — | `model_series_id`, `manufacturer_id` (pour enrichir le contexte) |

**Réponse `/articles/search`** :
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

**Réponse `/articles/{id}`** :
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

### Authentification

```
Header : X-Api-Key: <clé_api>
```

Toutes les requêtes non authentifiées retournent `401 Unauthorized`. L'API est à usage interne — pas de rate limiting strict requis côté sync, mais un throttle raisonnable côté recherche live (ex. 5 req/s par clé).

### Implémentation Odoo — `catalog.api.service`

```python
# models/catalog_api.py
class CatalogApiService(models.AbstractModel):
    _name = "catalog.api.service"
    _description = "Service d'accès à l'API catalogue pièces"

    def _request(self, path, params=None):
        """Appel HTTP sécurisé avec timeout et gestion d'erreurs."""
        import requests
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = ICP.get_param("garage_parts_catalog.api_url", "").rstrip("/")
        api_key  = ICP.get_param("garage_parts_catalog.api_key", "")
        timeout  = int(ICP.get_param("garage_parts_catalog.timeout", "15"))
        try:
            resp = requests.get(
                f"{base_url}/{path.lstrip('/')}",
                headers={"X-Api-Key": api_key},
                params=params or {},
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            raise UserError(_("Le catalogue pièces ne répond pas. Réessayez plus tard."))
        except requests.HTTPError as e:
            raise UserError(_("Erreur catalogue : %(err)s", err=str(e)))

    # --- Sync ---
    def sync_manufacturers(self): ...
    def sync_model_series(self): ...   # paginated
    def sync_car_types(self): ...      # paginated — volume ~100k
    def sync_groups(self): ...

    # --- Live search ---
    def search_articles(self, car_type_id, group_id=None, q=None, offset=0, limit=20): ...
    def get_article_details(self, article_id, **ctx): ...
```

---

## 6. Wizard de Recherche — `wizard.parts.catalog.search`

### Modèle TransientModel

```python
class WizardPartsCatalogSearch(models.TransientModel):
    _name = "wizard.parts.catalog.search"

    repair_order_id     = Many2one("repair.order", required=True)
    # Étape 1 — Sélection véhicule
    manufacturer_id     = Many2one("catalog.manufacturer")
    model_series_id     = Many2one("catalog.model.series")  # domain=[('manufacturer_id','=',manufacturer_id)]
    car_type_id         = Many2one("catalog.car.type")      # domain=[('model_series_id','=',model_series_id)]
    save_car_type       = Boolean  # "Mémoriser cette motorisation pour ce véhicule"
    # Étape 2 — Filtre catégorie + recherche texte
    primary_group_id    = Many2one("catalog.group", domain sur primary_group_name)
    group_id            = Many2one("catalog.group")
    search_query        = Char
    # Résultats (stockage JSON dans le transient)
    results_json        = Text  # JSON list d'articles (pour l'affichage OWL)
    results_count       = Integer
    results_offset      = Integer (pagination)
    # Étape 3 — Article sélectionné
    selected_article_json = Text  # JSON de l'article_details complet
    # Étape 4 — Ajout à l'OR
    qty_to_add          = Float, default=1.0
    uom_id              = Many2one("uom.uom")
    # état de navigation
    step                = Selection([vehicle_select, search, detail, confirm])
```

### Méthodes principales

```python
action_search()           # appelle search_articles, stocke dans results_json
action_next_page()        # pagination
action_select_article()   # appelle get_article_details, passe à step=detail
action_add_to_order()     # crée/trouve le produit Odoo, crée le stock.move sur l'OR
action_back()             # navigation retour
```

---

## 7. Flux UX Détaillé

```
[Bouton "Catalogue pièces" sur onglet Pièces de l'OR]
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 1 — SÉLECTION VÉHICULE                               │
│                                                             │
│  Fabricant : [AUDI ▼]  ← pré-rempli si véhicule de l'OR    │
│  Série     : [A4 (B9) ▼]  ← filtré par fabricant           │
│  Moteur    : [2.0 TDI 150 PS ▼]  ← filtré par série        │
│  ☐ Mémoriser ce moteur pour ce véhicule                     │
│                                                             │
│                     [Annuler]  [Rechercher →]               │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 2 — RECHERCHE PIÈCES                                 │
│                                                             │
│  Catégorie : [Freinage ▼]                                   │
│  Sous-cat  : [Disques de frein ▼]                           │
│  Recherche : [___________________________]  [🔍 Chercher]   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ [img] Disque de frein BOSCH 0986479504               │   │
│  │        OEM: 4F0615301D • EAN: 3165143396929          │   │
│  │        [Voir détails]  [+ Ajouter]                   │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ [img] Disque de frein BREMBO 09.A503.11              │   │
│  │        OEM: 4F0615301E                               │   │
│  │        [Voir détails]  [+ Ajouter]                   │   │
│  └─────────────────────────────────────────────────────┘   │
│  Page 1/5  [◀ Précédent]  [Suivant ▶]                       │
│            [← Modifier véhicule]                            │
└─────────────────────────────────────────────────────────────┘
         │ [Voir détails]
         ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 3 — FICHE ARTICLE                                    │
│                                                             │
│  [Photos carousel]                                          │
│  Nom   : Disque de frein BOSCH                              │
│  Réf.  : 0986479504                                         │
│  OEM   : 4F0615301D (AUDI), 4F0615301D (VW)                │
│  EAN   : 3165143396929                                      │
│  Specs : Diamètre [mm]: 320  Épaisseur [mm]: 30 ...         │
│  Compatibilité : AUDI A4 (B7) 2.0 TDI, AUDI A6 ...         │
│                                                             │
│  ✅ Produit Odoo existant trouvé : BOSCH 0986479504          │
│  — OU —                                                     │
│  ℹ️  Nouveau produit — sera créé à l'ajout                   │
│                                                             │
│  [← Retour aux résultats]  [+ Ajouter à l'OR →]             │
└─────────────────────────────────────────────────────────────┘
         │ [+ Ajouter à l'OR]
         ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 4 — CONFIRMATION                                     │
│                                                             │
│  Article  : Disque de frein BOSCH 0986479504                │
│  Quantité : [2.00]  Unité : [pce ▼]                         │
│                                                             │
│  [Annuler]  [✓ Confirmer et ajouter à l'OR]                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Logique de Correspondance Véhicule

### Pré-remplissage automatique du wizard

Quand le wizard s'ouvre depuis un OR qui a un `vehicle_id` :

1. **Fabricant** : `vehicle_id.catalog_manufacturer_id` → pré-sélectionne directement.  
   Fallback : cherche `catalog.manufacturer` lié via `vehicle_brand_ids` à `vehicle_id.brand_id`.

2. **Série** : `vehicle_id.catalog_model_series_id` → pré-sélectionne directement.  
   (vide si non renseigné — l'utilisateur choisit)

3. **Motorisation** : `vehicle_id.catalog_car_type_id` → pré-sélectionne directement.  
   (vide si non renseigné — l'utilisateur choisit)

4. **Case "Mémoriser"** : si cochée, met à jour les 3 champs `catalog_*` sur le `garage.vehicle`.

> ✅ Avec les 3 champs `catalog_*` sur `garage.vehicle`, un véhicule enregistré une fois est **entièrement pré-rempli** dans tous les ORs futurs — zéro clic sur l'étape 1.

### Configuration initiale du mapping marques

L'administrateur doit créer le lien entre :
- `garage.vehicle.brand` (marques locales — ex. "Audi")
- `catalog.manufacturer` (catalogue externe — ex. "AUDI", id=5)

**Interface** : dans la fiche de chaque `catalog.manufacturer`, un champ  
`vehicle_brand_ids` (Many2many) permet de sélectionner les marques locales correspondantes.

**Alternative rapide** : action serveur "Auto-mapper par nom" qui fait un ILIKE sur les noms.

> Ce mapping n'est nécessaire que pour le fallback. Si `catalog_manufacturer_id` est renseigné sur le véhicule, le mapping n'est pas consulté.

---

## 9. Logique de Correspondance & Création Produit

### Ordre de recherche d'un produit existant

Quand l'utilisateur clique "Ajouter à l'OR", le système cherche un `product.product` existant par ordre de priorité :

1. `catalog_article_id = article.article_id` → correspondance exacte catalogue
2. `barcode IN ean_numbers` → correspondance par EAN
3. `default_code = part_number` → correspondance par référence interne

### Si produit trouvé

→ Utilise directement le produit existant (pas de doublon créé).

### Si produit non trouvé → Création automatique

```
product.template créé avec :
  name              ← part_name (ex. "Disque de frein")
  default_code      ← part_number (ex. "0986479504")
  barcode           ← premier EAN de ean_numbers (si disponible)
  type              ← 'consu' (consommable — pas de gestion de stock par défaut)
  categ_id          ← catégorie produit configurée dans les paramètres
                       (défaut: "Pièces Auto" à créer si absente)
  description       ← concaténation des technical_details (clé: valeur)
  catalog_article_id ← article_id
  catalog_part_number ← part_number
  catalog_manufacturer_name ← article_manufacturer
  image_1920        ← téléchargée depuis thumbnail_url (si disponible)
```

> ⚠️ Le téléchargement de l'image au moment de la création produit est synchrone.  
> Envisager de ne pas télécharger l'image par défaut et laisser l'utilisateur choisir.

### Ajout à l'OR (stock.move)

Après création/résolution du produit, on crée un `stock.move` lié à l'OR :

```python
self.env["stock.move"].create({
    "repair_id": repair_order.id,
    "product_id": product.id,
    "product_uom_qty": wizard.qty_to_add,
    "product_uom": wizard.uom_id.id,
    "repair_line_type": "add",
    "location_id": repair_order.location_id.id,
    "location_dest_id": repair_order.location_dest_id.id,
    "name": product.name,
})
```

---

## 10. Synchronisation des Données de Référence

### Données à synchroniser localement

| Table | Volume estimé | Stratégie | Durée estimée |
|---|---|---|---|
| `manufacturers` | ~200 lignes | Sync initiale + manuelle | < 1s |
| `model_series` | ~15 000 lignes | Sync initiale paginée + manuelle | ~5s |
| `car_types` | **~100 000 lignes** | **Sync initiale paginée + manuelle** | ~30-60s |
| `groups` | ~500 lignes | Sync initiale + manuelle | < 1s |
| `articles` | Millions | **JAMAIS** cachées — recherche live uniquement | — |

> ⚠️ **Sync `car_types`** : ~100k lignes paginées par lots de 500. La première synchro peut durer jusqu'à 60s. Elle est exécutée en tâche de fond via `ir.actions.server` ou un job planifié — jamais de façon bloquante.

### Ordre de synchronisation obligatoire

```
1. manufacturers  (indépendant)
2. groups         (indépendant)
3. model_series   (dépend de manufacturers — FK)
4. car_types      (dépend de model_series et manufacturers — FK)
```

### Actions de synchronisation

```xml
<!-- data/catalog_sync_actions.xml -->
<record id="action_sync_all" model="ir.actions.server">
    name="Synchronisation complète du catalogue"
    code="
        env['catalog.manufacturer'].sync_from_api()
        env['catalog.group'].sync_from_api()
        env['catalog.model.series'].sync_from_api()
        env['catalog.car.type'].sync_from_api()  # en dernier — volume important
    "
</record>
```

Ces actions sont disponibles dans **Configuration → Catalogue pièces → Synchroniser**.  
La synchro complète est déclenchée automatiquement à l'installation du module (post-init hook).  
Une synchro incrémentale (si l'API supporte un paramètre `?updated_since=`) est envisageable en v2.

---

## 11. Stratégie de Cache & Performance

| Donnée | Stockage | Durée |
|---|---|---|
| Fabricants | `catalog.manufacturer` (DB) | Permanent — sync manuelle |
| Séries | `catalog.model.series` (DB) | Permanent — sync manuelle |
| **Motorisations** | **`catalog.car.type` (DB)** | **Permanent — sync manuelle (~100k lignes)** |
| Catégories | `catalog.group` (DB) | Permanent — sync manuelle |
| Résultats de recherche articles | Champ Text sur wizard transient | Durée du wizard |
| Fiche article détaillée | Champ Text sur wizard transient | Durée du wizard |

> **Décision de design** : Toutes les données de référence (fabricants, séries, motorisations, catégories) sont pré-chargées en base Odoo. La sélection dans le wizard et sur la fiche véhicule est donc **100% locale** — aucun appel API pour les dropdowns. Seule la recherche d'articles reste live.

### Index DB recommandés sur `catalog_car_type`

```sql
CREATE INDEX ON catalog_car_type (model_series_id);
CREATE INDEX ON catalog_car_type (manufacturer_id);
CREATE UNIQUE INDEX ON catalog_car_type (external_id);
```

Odoo crée automatiquement l'index sur `id` (PK). Les index ci-dessus sont à déclarer via `_sql_constraints` ou un `post_init_hook`.

---

---

## 12. Enrichissement du Formulaire Véhicule (`garage.vehicle`)

### Objectif

La fiche véhicule devient le point central de configuration catalogue. Une fois la motorisation définie sur le véhicule, tous les ORs futurs sont pré-remplis automatiquement sans aucune saisie.

### Nouveaux champs sur `garage.vehicle`

| Champ | Type | Notes |
|---|---|---|
| `catalog_manufacturer_id` | Many2one(`catalog.manufacturer`) | Fabricant dans le catalogue |
| `catalog_model_series_id` | Many2one(`catalog.model.series`) | Série catalogue (domain: fabricant) |
| `catalog_car_type_id` | Many2one(`catalog.car.type`) | Motorisation exacte (domain: série) |

### UI — Onglet ou section « Catalogue pièces » sur la fiche véhicule

```
┌─────────────────────────────────────────────────────────────────┐
│  FICHE VÉHICULE  ·  AUDI A4 2019 — AA-123-BB                   │
├──────────────────┬──────────────────────────────────────────────┤
│  Infos générales │  Catalogue pièces  │  Historique  │  ...     │
└──────────────────┴──────────────────────────────────────────────┘

  [Onglet Catalogue pièces]

  Fabricant catalogue : [AUDI ▼]             ← catalog.manufacturer
  Modèle catalogue    : [A4 (B9) 2015-2020 ▼] ← filtré par fabricant
  Motorisation        : [2.0 TDI 150 CV ▼]   ← filtré par modèle

  ℹ️  Ces informations permettent de pré-remplir automatiquement
      la recherche dans le catalogue lors des ordres de réparation.

  [🔍 Tester la recherche catalogue]
```

> Le bouton **"Tester la recherche catalogue"** ouvre directement le wizard au step 2 (recherche) avec la motorisation déjà sélectionnée — utile pour valider la configuration du véhicule.

### Comportement des cascades (onchange)

```python
@api.onchange("catalog_manufacturer_id")
def _onchange_catalog_manufacturer(self):
    self.catalog_model_series_id = False
    self.catalog_car_type_id = False
    return {"domain": {
        "catalog_model_series_id": [("manufacturer_id", "=", self.catalog_manufacturer_id.id)]
    }}

@api.onchange("catalog_model_series_id")
def _onchange_catalog_model_series(self):
    self.catalog_car_type_id = False
    return {"domain": {
        "catalog_car_type_id": [("model_series_id", "=", self.catalog_model_series_id.id)]
    }}

@api.onchange("brand_id")
def _onchange_brand_id_catalog(self):
    """Pré-remplit catalog_manufacturer_id si la marque est liée à un fabricant catalogue."""
    if self.brand_id and not self.catalog_manufacturer_id:
        manufacturer = self.env["catalog.manufacturer"].search(
            [("vehicle_brand_ids", "in", self.brand_id.id)], limit=1
        )
        self.catalog_manufacturer_id = manufacturer
```

### Vue XML (héritage sur `garage.vehicle` form)

```xml
<!-- views/garage_vehicle_views.xml -->
<record id="view_garage_vehicle_catalog_form" model="ir.ui.view">
    <field name="model">garage.vehicle</field>
    <field name="inherit_id" ref="repair_auto.view_garage_vehicle_form"/>
    <field name="arch" type="xml">
        <notebook position="inside">
            <page string="Catalogue pièces" name="catalog">
                <group>
                    <field name="catalog_manufacturer_id"
                           options="{'no_create': True}"/>
                    <field name="catalog_model_series_id"
                           options="{'no_create': True}"
                           domain="[('manufacturer_id','=',catalog_manufacturer_id)]"/>
                    <field name="catalog_car_type_id"
                           options="{'no_create': True}"
                           domain="[('model_series_id','=',catalog_model_series_id)]"/>
                </group>
                <div class="text-muted" style="font-size:0.9em; margin-top:8px">
                    <i class="fa fa-info-circle"/>
                    Ces informations pré-remplissent la recherche catalogue dans les ordres de réparation.
                </div>
                <button name="action_test_catalog_search" type="object"
                        string="Tester la recherche catalogue"
                        class="btn-secondary"
                        attrs="{'invisible': [('catalog_car_type_id','=',False)]}"/>
            </page>
        </notebook>
    </field>
</record>
```

### Affichage synthétique sur l'OR

Quand un OR a un véhicule avec `catalog_car_type_id` renseigné, afficher une ligne d'info dans le formulaire OR :

```
Motorisation catalogue : AUDI A4 (B9) — 2.0 TDI 150 CV [2015–2020]  [Modifier]
```

Ce lien "Modifier" ouvre la fiche véhicule directement sur l'onglet Catalogue pièces.

---

## 13. Sécurité

| Action | Groupe autorisé |
|---|---|
| Ouvrir le wizard catalogue | Réception + Responsable |
| Ajouter une pièce depuis le catalogue | Réception + Responsable |
| Synchroniser les données de référence | Responsable uniquement |
| Configurer l'API (URL/clé) | Admin Odoo uniquement (`base.group_system`) |
| Voir les fabricants/catégories | Technicien (lecture seule) |

> La clé API est stockée dans `ir.config_parameter` avec `groups=base.group_system` — inaccessible depuis l'interface aux non-admins.

---

## 14. OWL Component Design

### Composant principal : `PartsCatalogWizard`

```
PartsCatalogWizard
  ├── VehicleSelectStep      # Étape 1 : cascades Select manufacturer → series → type
  ├── ArticleSearchStep      # Étape 2 : filtres catégorie + recherche + grille résultats
  │    ├── CategoryFilter    # Dropdowns hiérarchiques primary → sub → sub-sub
  │    └── ArticleCard       # Carte résultat (image, nom, ref, boutons)
  ├── ArticleDetailStep      # Étape 3 : fiche complète + carousel images
  └── AddToOrderStep         # Étape 4 : quantité + confirmation
```

### Points techniques OWL 18 à respecter

- Utiliser `useService("dialog")` pour ouvrir le wizard en modal pleine largeur
- Les cascades de Select (fabricant → série → type) utilisent `onchange` via `orm.call()`
- Le carousel d'images : composant léger sans dépendance externe
- La grille de résultats : 3 colonnes responsive avec `t-foreach`
- Pagination : `offset/limit` passés au contrôleur Python via `orm.call()`

---

## 15. Questions Ouvertes (Décisions requises avant implémentation)

### Décidées dans cette version du plan

| Question | Décision retenue |
|---|---|
| Cache des `car_types` en DB ou à la demande ? | ✅ **En DB** — pré-chargés intégralement |
| API REST ou accès direct PostgreSQL ? | ✅ **REST** — API à créer pour servir Odoo |
| `car_type_id` sur `garage.vehicle` : Integer ou Many2one ? | ✅ **Many2one** vers `catalog.car.type` |
| Formulaire véhicule enrichi ? | ✅ **Oui** — onglet "Catalogue pièces" avec 3 cascades |

### Questions encore ouvertes

| # | Question | Options | Impact |
|---|---|---|---|
| 1 | **Authentification API** : X-Api-Key header, Bearer token, ou autre ? | À choisir lors de la création de l'API | Headers des requêtes |
| 2 | **Téléchargement image produit** : synchrone, async (job), ou jamais auto ? | Sync (simple) / Async (mieux pour perfs) / Désactivé par défaut | UX et performances |
| 3 | **Catégorie produit** des nouvelles pièces créées : fixe "Pièces Auto" ou configurable dans les paramètres ? | Configurable (recommandé) | Organisation produits |
| 4 | **Type de produit** créé : `consu` (consommable) ou `product` (stockable) ? | `consu` recommandé (pas de gestion stock) / `product` si gestion stock souhaitée | Gestion de stock |
| 5 | **Sync incrémentale** : l'API exposera-t-elle un paramètre `?updated_since=` pour les mises à jour partielles ? | Oui (à planifier dès la création API) / Non (sync complète seulement) | Durée des mises à jour futures |
| 6 | **Gestion offline** : comportement si l'API articles est indisponible pendant la recherche ? | Message d'erreur explicite (minimum) / Retry automatique | UX |
| 7 | **Langue des données** : les noms d'articles/groupes sont-ils multilingues dans la DB source, ou uniquement en français/anglais ? | À vérifier dans les données source | i18n du catalogue |

---

---

## 16. Fichiers de Référence dans `.github/ai/`

| Fichier | Contenu |
|---|---|
| `parts-catalog-integration.md` | **Ce fichier** — spec architecture |
| `parts-catalog-roadmap.md` | Roadmap d'implémentation phase par phase |
| `user-stories/parts-catalog.md` | User stories détaillées avec critères d'acceptation |
| `repair_auto-module.md` | Module principal `repair_auto` (dont dépend ce module) |
| `project-harness.md` | Vue d'ensemble projet |
