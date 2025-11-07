# Traducteur Multilingue

[English](../README.md) | [中文](README_ZH.md) | [日本語](README_JA.md) | [Français](README_FR.md) | [Deutsch](README_DE.md) | [한국어](README_KO.md)

---

Outil de traduction de bureau alimenté par l'IA avec support de plusieurs fournisseurs d'API, déclenché par un raccourci global (triple-appui sur Espace).

- **Flux de travail**: Copier le texte → Triple-appui sur Espace → Traduction et remplacement automatiques
- **Plateforme cible**: Windows 10/11 (x64)

---

## ✨ Fonctionnalités Principales

- **Support de Plusieurs Fournisseurs d'IA**: Chargement dynamique de Google Gemini, Anthropic Claude, OpenAI et tous les services d'API compatibles OpenAI.
- **Raccourci Global**: Déclenchez la traduction avec un triple-appui sur Espace dans n'importe quel champ de saisie sans changer de fenêtre.
- **Système de Cache Intelligent**: Cache à double couche haute performance (LRU en mémoire + persistance SQLite) pour réduire considérablement les appels API et les coûts.
- **Traduction Contextuelle**: Distingue différents contextes de conversation en fonction des titres des fenêtres actuelles pour des traductions cohérentes.
- **Évaluation de la Qualité de Traduction**: Évalue automatiquement la qualité de la traduction et réessaie intelligemment lorsque la qualité est insuffisante.
- **Architecture Asynchrone Robuste**: Utilise `asyncio` et le multi-threading pour des requêtes concurrentes haute performance et une expérience utilisateur fluide.
- **Gestion Avancée de la Configuration**:
  - Validation stricte de la configuration à l'aide de modèles Pydantic.
  - Repli automatique vers le répertoire personnel de l'utilisateur lorsque le répertoire du programme n'est pas accessible en écriture.
- **Gestion Sécurisée des Clés**: Outil de chiffrement AES-GCM intégré pour le stockage sécurisé des clés API.
- **Outils pour Développeurs**: Console d'exécution riche en fonctionnalités prenant en charge le changement de mode, le rechargement de configuration à chaud, les contrôles de santé des API et les diagnostics réseau.
- **Programme de Démarrage Robuste**: Gère automatiquement les dépendances de bibliothèque dynamique OpenSSL, l'affichage haute DPI et le nettoyage des fichiers temporaires dans les environnements Windows.

---

## 🚀 Flux de Travail Principal

![Animation de Démonstration](动画演示.gif)

1.  **Déclencher la Traduction**: L'utilisateur triple-appuie sur Espace dans le champ de saisie de n'importe quelle application pour activer la traduction.
2.  **Obtenir le Texte**: Le programme récupère automatiquement le texte depuis le presse-papiers du système.
3.  **Traitement Intelligent**:
    - **Détection de la Langue**: Identifie automatiquement la langue source.
    - **Requête de Cache**: Recherche d'abord dans le cache mémoire, puis dans la base de données SQLite ; renvoie immédiatement si trouvé.
    - **Appel d'API**: Si le cache échoue, appelle les API des fournisseurs d'IA dans l'ordre configuré pour la traduction.
    - **Évaluation de la Qualité**: Évalue la qualité de la traduction renvoyée par l'API ; essaie automatiquement le prochain fournisseur d'API configuré si la qualité est insuffisante.
4.  **Remplacement du Résultat**: La traduction finale est automatiquement remplacée dans le champ de saisie actuel de l'utilisateur.

---

## 🛠️ Environnement et Installation

- **Système**: Windows 10/11 (x64)
- **Dépendances**: Python 3.11 ou 3.12, Poetry

**Démarrage Rapide:**

```bash
# 1. Installer les dépendances
# Environnement Python 3.11 ou 3.12 recommandé
pip install poetry
poetry install
poetry shell

# 2. Configurer les clés API (étape critique)
# Au moins une clé API doit être configurée avant de démarrer le programme
# Exécutez la commande suivante et suivez les instructions du menu
poetry run python -m utils.api_key_tool

# 3. Démarrer le programme
poetry run python start.py
```

**⚠️ Notes Importantes:**

- **Les Clés API Doivent Être Chiffrées**: Vous **devez** utiliser `api_key_tool` pour chiffrer et définir vos clés API avant de démarrer le programme. Les clés brutes non chiffrées ne sont pas acceptées.
- **Fichiers de Configuration**: Au premier démarrage, le programme génère automatiquement trois fichiers de configuration dans le répertoire `config/`: `config.yaml`, `mode_config.yaml`, `models.yaml`. Vous pouvez les modifier selon vos besoins.

---

## 📁 Structure du Projet

```
.
├── start.py                            # 🔑 Point d'entrée de l'application : gère la compatibilité de plateforme (OpenSSL, reconnaissance DPI, résolution de chemin)
├── pyproject.toml                      # 📦 Dépendances Poetry et configuration du projet
├── README.md                           # 📖 Documentation du projet
├── AGENTS.md                           # 🤖 Guide de développement d'assistant IA
├── config/                             # ⚙️ Répertoire de configuration généré à l'exécution
│   ├── config.yaml                     # Configuration principale : contrôle le comportement de l'application, réseau, journalisation, etc.
│   ├── mode_config.yaml                # Configuration de mode : définit les modes de traduction, fonctionnalités linguistiques et invites
│   └── models.yaml                     # Configuration API : gère tous les fournisseurs d'IA et modèles
├── core/                               # 🧠 Couche logique de base (architecture asynchrone)
│   ├── main.py                         # 🎯 Gestion du cycle de vie de l'application et gestion globale des exceptions
│   ├── async_utils.py                  # 🔄 Utilitaires asynchrones : exécute et gère la boucle d'événements dans un thread dédié
│   ├── translation_engine.py           # 🧠 Moteur de traduction : intègre la détection de langue, mise en cache, appels API et contrôle qualité
│   ├── prompt_builder.py               # 💬 Constructeur d'invite intelligent
│   ├── config_management.py            # 🗂️ Gestion avancée de configuration : validation Pydantic, repli de chemin, génération automatique
│   ├── cache_manager.py                # 💾 Système de cache hybride : LRU mémoire + persistance SQLite
│   ├── keyboard_listener.py            # ⌨️ Écouteur de clavier global
│   ├── gui_handler.py                  # 🎨 Gestionnaire d'interface graphique (PyQt6)
│   ├── console_interface.py            # 💻 Console interactive d'exécution
│   ├── service_manager.py              # 🛠️ Gestionnaire de service : gestion unifiée du réseau, API, cache, etc.
│   ├── context_manager.py              # 🗣️ Gestionnaire de contexte : implémente l'historique de conversation conscient des fenêtres
│   ├── language_detection.py           # 🌍 Détection de langue multi-algorithmes
│   ├── window_utils.py                 # 🪟 Utilitaires de fenêtre multiplateforme
│   ├── cleanup_utils.py                # 🧹 Tâches de nettoyage planifiées en arrière-plan (cache, contexte)
│   ├── logging_config.py               # 📝 Système de journalisation unifié et nettoyage de données sensibles
│   ├── quality_assessment.py           # 📊 Moteur d'évaluation de qualité de traduction
│   ├── response_parser.py              # 📄 Analyseur de réponse API (secours)
│   ├── rules_engine.py                 # 📜 Moteur de règles expert : gère les règles de traduction pour des paires de langues spécifiques
│   ├── text_utils.py                   # 🔤 Utilitaires de traitement de texte de base
│   ├── network_utils.py                # 🌐 Utilitaires réseau : contexte SSL, vérifications de connexion
│   ├── retry_utils.py                  # 🔄 Utilitaires de nouvelle tentative de requête API unifiés
│   ├── api_manager.py                  # 🔗 Gestionnaire d'API : chargement et planification dynamiques de plusieurs fournisseurs
│   ├── constants.py                    # 📋 Constantes d'application (source de version autoritaire)
│   └── api_providers/                  # 🤖 Couche d'implémentation de fournisseur d'API IA
│       ├── base.py                     # 🔧 Classe de base abstraite de fournisseur
│       ├── gemini.py                   # 🌐 Client API Google Gemini
│       ├── openai.py                   # 🚀 Client API OpenAI et compatible
│       └── anthropic.py                # 📖 Client API Anthropic Claude
├── utils/                              # 🛠️ Outils en ligne de commande
│   ├── api_crypto.py                   # 🔐 Implémentation de base du chiffrement AES-GCM
│   └── api_key_tool.py                 # 🗝️ Outil de gestion de clés API
├── test/                               # 🧪 Modules de test
│   └── test_core_workflow.py           # 🔧 Tests de flux de travail principal
└── openssl_dll/                        # 🔧 Dépendances OpenSSL Windows PyInstaller
```

---

## 💡 Dépannage

- **Impossible de Déclencher la Traduction**:
  - Vérifiez si au moins une clé API chiffrée est configurée dans `config/models.yaml`.
  - Assurez-vous qu'aucun autre programme n'occupe le hook de clavier global.
- **Échec de la Traduction**:
  - Après le démarrage du programme, sélectionnez l'option `7` (contrôle de santé API) dans la console pour vérifier la disponibilité du service API.
  - Consultez `logs/app.log` pour des informations d'erreur détaillées.
- **Problèmes de Permissions**:
  - Si le programme ne peut pas créer les dossiers `config`, `logs`, `data` dans le répertoire actuel, il tentera automatiquement de les créer dans le répertoire personnel de l'utilisateur (`C:/Users/YourUsername/.multitranslator`). Assurez-vous qu'au moins un de ces emplacements est accessible en écriture.

---

## 📄 Licence

MIT License
