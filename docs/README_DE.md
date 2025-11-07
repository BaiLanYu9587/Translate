# Mehrsprachiger Übersetzer

[English](../README.md) | [中文](README_ZH.md) | [日本語](README_JA.md) | [Français](README_FR.md) | [Deutsch](README_DE.md) | [한국어](README_KO.md)

---

KI-gestütztes Desktop-Übersetzungstool mit Unterstützung für mehrere API-Anbieter, aktiviert durch globalen Hotkey (dreimaliges Drücken der Leertaste).

- **Arbeitsablauf**: Text kopieren → Dreimal Leertaste drücken → Automatische Übersetzung und Ersetzung
- **Zielplattform**: Windows 10/11 (x64)

---

## ✨ Hauptmerkmale

- **Unterstützung mehrerer KI-Anbieter**: Dynamisches Laden von Google Gemini, Anthropic Claude, OpenAI und allen OpenAI-kompatiblen API-Diensten.
- **Globaler Hotkey**: Übersetzung durch dreimaliges Drücken der Leertaste in jedem Eingabefeld auslösen, ohne Fenster zu wechseln.
- **Intelligentes Cache-System**: Hochleistungs-Zweischicht-Cache (Speicher-LRU + SQLite-Persistierung) zur dramatischen Reduzierung von API-Aufrufen und Kosten.
- **Kontextbewusste Übersetzung**: Unterscheidet verschiedene Gesprächskontexte basierend auf aktuellen Fenstertiteln für kohärente Übersetzungen.
- **Bewertung der Übersetzungsqualität**: Bewertet automatisch die Qualität der Übersetzung und versucht es intelligent erneut, wenn die Qualität unzureichend ist.
- **Robuste asynchrone Architektur**: Nutzt `asyncio` und Multi-Threading für hochleistungsfähige gleichzeitige Anfragen und reibungslose Benutzererfahrung.
- **Erweiterte Konfigurationsverwaltung**:
  - Strenge Konfigurationsvalidierung mit Pydantic-Modellen.
  - Automatische Rückfallmöglichkeit auf Benutzer-Home-Verzeichnis, wenn Programmverzeichnis nicht beschreibbar ist.
- **Sichere Schlüsselverwaltung**: Eingebautes AES-GCM-Verschlüsselungstool für sichere API-Schlüsselspeicherung.
- **Entwickler-Tools**: Funktionsreiche Laufzeitkonsole mit Unterstützung für Moduswechsel, Hot-Config-Reload, API-Gesundheitschecks und Netzwerkdiagnose.
- **Robustes Startprogramm**: Behandelt automatisch OpenSSL-Dynamic-Library-Abhängigkeiten, High-DPI-Display und temporäre Dateiaufräumung in Windows-Umgebungen.

---

## 🚀 Kern-Arbeitsablauf

![Demo-Animation](动画演示.gif)

1.  **Übersetzung auslösen**: Benutzer drückt dreimal die Leertaste im Eingabefeld einer beliebigen Anwendung, um die Übersetzung zu aktivieren.
2.  **Text abrufen**: Programm ruft automatisch Text aus der Systemzwischenablage ab.
3.  **Intelligente Verarbeitung**:
    - **Spracherkennung**: Identifiziert automatisch die Quellsprache.
    - **Cache-Abfrage**: Durchsucht zuerst den Speicher-Cache, dann die SQLite-Datenbank; gibt sofort zurück, wenn gefunden.
    - **API-Aufruf**: Wenn Cache nicht trifft, ruft die APIs der KI-Anbieter in konfigurierter Reihenfolge zur Übersetzung auf.
    - **Qualitätsbewertung**: Bewertet die von der API zurückgegebene Übersetzungsqualität; versucht automatisch den nächsten konfigurierten API-Anbieter, wenn die Qualität unzureichend ist.
4.  **Ergebnisersetzung**: Die endgültige Übersetzung wird automatisch in das aktuelle Eingabefeld des Benutzers eingefügt.

---

## 🛠️ Umgebung & Installation

- **System**: Windows 10/11 (x64)
- **Abhängigkeiten**: Python 3.11 oder 3.12, Poetry

**Schnellstart:**

```bash
# 1. Abhängigkeiten installieren
# Python 3.11 oder 3.12 Umgebung empfohlen
pip install poetry
poetry install
poetry shell

# 2. API-Schlüssel konfigurieren (kritischer Schritt)
# Mindestens ein API-Schlüssel muss vor dem Programmstart konfiguriert werden
# Führen Sie den folgenden Befehl aus und folgen Sie den Menüanweisungen
poetry run python -m utils.api_key_tool

# 3. Programm starten
poetry run python start.py
```

**⚠️ Wichtige Hinweise:**

- **API-Schlüssel müssen verschlüsselt werden**: Sie **müssen** `api_key_tool` verwenden, um Ihre API-Schlüssel zu verschlüsseln und einzustellen, bevor Sie das Programm starten. Rohe unverschlüsselte Schlüssel werden nicht akzeptiert.
- **Konfigurationsdateien**: Beim ersten Start generiert das Programm automatisch drei Konfigurationsdateien im `config/`-Verzeichnis: `config.yaml`, `mode_config.yaml`, `models.yaml`. Sie können diese nach Bedarf ändern.

---

## 📁 Projektstruktur

```
.
├── start.py                            # 🔑 Anwendungseinstiegspunkt: behandelt Plattformkompatibilität (OpenSSL, DPI-Awareness, Pfadauflösung)
├── pyproject.toml                      # 📦 Poetry-Abhängigkeiten & Projektkonfiguration
├── README.md                           # 📖 Projektdokumentation
├── AGENTS.md                           # 🤖 KI-Assistenten-Entwicklungsleitfaden
├── config/                             # ⚙️ Laufzeit-generiertes Konfigurationsverzeichnis
│   ├── config.yaml                     # Hauptkonfiguration: steuert App-Verhalten, Netzwerk, Logging usw.
│   ├── mode_config.yaml                # Moduskonfiguration: definiert Übersetzungsmodi, Sprachfunktionen und Prompts
│   └── models.yaml                     # API-Konfiguration: verwaltet alle KI-Anbieter und Modelle
├── core/                               # 🧠 Kern-Logikschicht (asynchrone Architektur)
│   ├── main.py                         # 🎯 Anwendungslebenszyklusverwaltung & globale Ausnahmebehandlung
│   ├── async_utils.py                  # 🔄 Asynchrone Dienstprogramme: führt und verwaltet Event-Loop in dediziertem Thread
│   ├── translation_engine.py           # 🧠 Übersetzungsmotor: integriert Spracherkennung, Caching, API-Aufrufe und Qualitätskontrolle
│   ├── prompt_builder.py               # 💬 Intelligenter Prompt-Builder
│   ├── config_management.py            # 🗂️ Erweiterte Konfigurationsverwaltung: Pydantic-Validierung, Pfad-Fallback, Auto-Generierung
│   ├── cache_manager.py                # 💾 Hybrid-Cache-System: Speicher-LRU + SQLite-Persistierung
│   ├── keyboard_listener.py            # ⌨️ Globaler Tastatur-Listener
│   ├── gui_handler.py                  # 🎨 GUI-Handler (PyQt6)
│   ├── console_interface.py            # 💻 Laufzeit-interaktive Konsole
│   ├── service_manager.py              # 🛠️ Service-Manager: einheitliche Verwaltung von Netzwerk, API, Cache usw.
│   ├── context_manager.py              # 🗣️ Kontext-Manager: implementiert fensterbewusste Gesprächshistorie
│   ├── language_detection.py           # 🌍 Multi-Algorithmus-Spracherkennung
│   ├── window_utils.py                 # 🪟 Plattformübergreifende Fenster-Dienstprogramme
│   ├── cleanup_utils.py                # 🧹 Hintergrund-geplante Aufräumaufgaben (Cache, Kontext)
│   ├── logging_config.py               # 📝 Einheitliches Logging-System & Bereinigung sensibler Daten
│   ├── quality_assessment.py           # 📊 Übersetzungsqualitäts-Bewertungsmotor
│   ├── response_parser.py              # 📄 API-Antwort-Parser (Fallback)
│   ├── rules_engine.py                 # 📜 Experten-Regel-Engine: behandelt Übersetzungsregeln für spezifische Sprachpaare
│   ├── text_utils.py                   # 🔤 Grundlegende Textverarbeitungs-Dienstprogramme
│   ├── network_utils.py                # 🌐 Netzwerk-Dienstprogramme: SSL-Kontext, Verbindungsprüfungen
│   ├── retry_utils.py                  # 🔄 Einheitliche API-Anfrage-Wiederholungs-Dienstprogramme
│   ├── api_manager.py                  # 🔗 API-Manager: dynamisches Laden und Scheduling mehrerer Anbieter
│   ├── constants.py                    # 📋 Anwendungskonstanten (autoritative Versionsquelle)
│   └── api_providers/                  # 🤖 KI-API-Anbieter-Implementierungsschicht
│       ├── base.py                     # 🔧 Anbieter abstrakte Basisklasse
│       ├── gemini.py                   # 🌐 Google Gemini API-Client
│       ├── openai.py                   # 🚀 OpenAI und kompatible API-Client
│       └── anthropic.py                # 📖 Anthropic Claude API-Client
├── utils/                              # 🛠️ Befehlszeilentools
│   ├── api_crypto.py                   # 🔐 AES-GCM-Verschlüsselung Kernimplementierung
│   └── api_key_tool.py                 # 🗝️ API-Schlüssel-Verwaltungstool
├── test/                               # 🧪 Testmodule
│   └── test_core_workflow.py           # 🔧 Haupt-Workflow-Tests
└── openssl_dll/                        # 🔧 Windows PyInstaller OpenSSL-Abhängigkeiten
```

---

## 💡 Fehlerbehebung

- **Übersetzung kann nicht ausgelöst werden**:
  - Prüfen Sie, ob mindestens ein verschlüsselter API-Schlüssel in `config/models.yaml` konfiguriert ist.
  - Stellen Sie sicher, dass kein anderes Programm den globalen Tastatur-Hook belegt.
- **Übersetzung schlägt fehl**:
  - Nach Programmstart wählen Sie Option `7` (API-Gesundheitscheck) in der Konsole, um die Verfügbarkeit des API-Dienstes zu überprüfen.
  - Prüfen Sie `logs/app.log` für detaillierte Fehlerinformationen.
- **Berechtigungsprobleme**:
  - Wenn das Programm keine `config`-, `logs`-, `data`-Ordner im aktuellen Verzeichnis erstellen kann, versucht es automatisch, sie im Benutzer-Home-Verzeichnis (`C:/Users/YourUsername/.multitranslator`) zu erstellen. Stellen Sie sicher, dass mindestens einer dieser Speicherorte beschreibbar ist.

---

## 📄 Lizenz

MIT License
