# 다국어 번역기

[English](../README.md) | [中文](README_ZH.md) | [日本語](README_JA.md) | [Français](README_FR.md) | [Deutsch](README_DE.md) | [한국어](README_KO.md)

---

여러 API 제공업체를 지원하는 AI 기반 데스크톱 번역 도구로, 전역 단축키(스페이스바 3번 탭)로 실행됩니다.

- **작동 방식**: 텍스트 복사 → 스페이스바 3번 탭 → 자동 번역 및 교체
- **대상 플랫폼**: Windows 10/11 (x64)

---

## ✨ 주요 기능

- **다중 AI 제공업체 지원**: Google Gemini, Anthropic Claude, OpenAI 및 모든 OpenAI 호환 API 서비스를 동적으로 로드합니다.
- **전역 단축키**: 창을 전환하지 않고도 모든 입력 필드에서 스페이스바를 3번 탭하여 번역을 실행할 수 있습니다.
- **지능형 캐시 시스템**: 고성능 이중 계층 캐시(메모리 LRU + SQLite 지속성)로 API 호출 및 비용을 크게 줄입니다.
- **컨텍스트 인식 번역**: 현재 창 제목을 기반으로 다양한 대화 컨텍스트를 구분하여 일관된 번역을 제공합니다.
- **번역 품질 평가**: 번역 결과의 품질을 자동으로 평가하고 품질이 부족할 때 지능적으로 재시도합니다.
- **견고한 비동기 아키텍처**: `asyncio` 및 멀티스레딩을 활용하여 고성능 동시 요청 및 원활한 사용자 경험을 실현합니다.
- **고급 구성 관리**:
  - Pydantic 모델을 사용한 엄격한 구성 검증.
  - 프로그램 디렉토리에 쓰기가 불가능한 경우 사용자 홈 디렉토리로 자동 폴백.
- **안전한 키 관리**: API 키의 안전한 저장을 위한 내장 AES-GCM 암호화 도구.
- **개발자 도구**: 모드 전환, 핫 구성 리로드, API 상태 검사, 네트워크 진단을 지원하는 기능이 풍부한 런타임 콘솔.
- **견고한 시작 프로그램**: Windows 환경에서 OpenSSL 동적 라이브러리 종속성, 고DPI 디스플레이 및 임시 파일 정리를 자동으로 처리합니다.

---

## 🚀 핵심 워크플로우

![데모 애니메이션](动画演示.gif)

1.  **번역 시작**: 사용자가 임의의 애플리케이션의 입력 필드에서 스페이스바를 3번 탭하여 번역 기능을 활성화합니다.
2.  **텍스트 가져오기**: 프로그램이 시스템 클립보드에서 번역할 텍스트를 자동으로 가져옵니다.
3.  **스마트 처리**:
    - **언어 감지**: 소스 언어를 자동으로 식별합니다.
    - **캐시 쿼리**: 먼저 메모리 캐시를 검색한 다음 SQLite 데이터베이스를 검색합니다. 히트하면 즉시 결과를 반환합니다.
    - **API 호출**: 캐시 미스 시 구성된 순서대로 AI 제공업체의 API를 호출하여 번역을 수행합니다.
    - **품질 평가**: API가 반환한 번역 결과의 품질을 점수화하고, 품질이 기준에 미달하면 다음에 구성된 API 제공업체를 자동으로 시도합니다.
4.  **결과 교체**: 최종 번역 결과가 사용자의 현재 입력 필드에 자동으로 교체됩니다.

---

## 🛠️ 환경 및 설치

- **시스템**: Windows 10/11 (x64)
- **종속성**: Python 3.11 또는 3.12, Poetry

**빠른 시작:**

```bash
# 1. 종속성 설치
# Python 3.11 또는 3.12 환경 권장
pip install poetry
poetry install
poetry shell

# 2. API 키 구성 (중요한 단계)
# 프로그램을 시작하기 전에 최소한 하나의 API 키를 구성해야 합니다
# 다음 명령을 실행하고 메뉴 지시를 따르세요
poetry run python -m utils.api_key_tool

# 3. 프로그램 시작
poetry run python start.py
```

**⚠️ 중요 사항:**

- **API 키는 암호화해야 합니다**: 프로그램을 시작하기 전에 `api_key_tool`을 사용하여 API 키를 암호화하고 설정**해야 합니다**. 암호화되지 않은 원시 키는 허용되지 않습니다.
- **구성 파일**: 프로그램이 처음 시작되면 `config/` 디렉토리에 `config.yaml`, `mode_config.yaml`, `models.yaml` 세 개의 구성 파일이 자동으로 생성됩니다. 필요에 따라 수정할 수 있습니다.

---

## 📁 프로젝트 구조

```
.
├── start.py                            # 🔑 애플리케이션 진입점: 플랫폼 호환성 처리(OpenSSL, DPI 인식, 경로 해결)
├── pyproject.toml                      # 📦 Poetry 종속성 및 프로젝트 구성
├── README.md                           # 📖 프로젝트 문서
├── AGENTS.md                           # 🤖 AI 어시스턴트 개발 가이드
├── config/                             # ⚙️ 런타임 생성 구성 디렉토리
│   ├── config.yaml                     # 주 구성: 앱 동작, 네트워크, 로깅 등 제어
│   ├── mode_config.yaml                # 모드 구성: 번역 모드, 언어 기능 및 프롬프트 정의
│   └── models.yaml                     # API 구성: 모든 AI 제공업체 및 모델 관리
├── core/                               # 🧠 핵심 로직 레이어(비동기 아키텍처)
│   ├── main.py                         # 🎯 애플리케이션 수명 주기 관리 및 전역 예외 처리
│   ├── async_utils.py                  # 🔄 비동기 유틸리티: 전용 스레드에서 이벤트 루프 실행 및 관리
│   ├── translation_engine.py           # 🧠 번역 엔진: 언어 감지, 캐싱, API 호출 및 품질 제어 통합
│   ├── prompt_builder.py               # 💬 지능형 프롬프트 빌더
│   ├── config_management.py            # 🗂️ 고급 구성 관리: Pydantic 검증, 경로 폴백, 자동 생성
│   ├── cache_manager.py                # 💾 하이브리드 캐시 시스템: 메모리 LRU + SQLite 지속성
│   ├── keyboard_listener.py            # ⌨️ 전역 키보드 리스너
│   ├── gui_handler.py                  # 🎨 GUI 핸들러(PyQt6)
│   ├── console_interface.py            # 💻 런타임 대화형 콘솔
│   ├── service_manager.py              # 🛠️ 서비스 관리자: 네트워크, API, 캐시 등의 통합 관리
│   ├── context_manager.py              # 🗣️ 컨텍스트 관리자: 창 인식 대화 기록 구현
│   ├── language_detection.py           # 🌍 다중 알고리즘 언어 감지
│   ├── window_utils.py                 # 🪟 크로스 플랫폼 창 유틸리티
│   ├── cleanup_utils.py                # 🧹 백그라운드 예약 정리 작업(캐시, 컨텍스트)
│   ├── logging_config.py               # 📝 통합 로깅 시스템 및 민감한 데이터 삭제
│   ├── quality_assessment.py           # 📊 번역 품질 평가 엔진
│   ├── response_parser.py              # 📄 API 응답 파서(폴백)
│   ├── rules_engine.py                 # 📜 전문가 규칙 엔진: 특정 언어 쌍의 번역 규칙 처리
│   ├── text_utils.py                   # 🔤 기본 텍스트 처리 유틸리티
│   ├── network_utils.py                # 🌐 네트워크 유틸리티: SSL 컨텍스트, 연결 확인
│   ├── retry_utils.py                  # 🔄 통합 API 요청 재시도 유틸리티
│   ├── api_manager.py                  # 🔗 API 관리자: 여러 제공업체의 동적 로딩 및 스케줄링
│   ├── constants.py                    # 📋 애플리케이션 상수(권위 있는 버전 소스)
│   └── api_providers/                  # 🤖 AI API 제공업체 구현 레이어
│       ├── base.py                     # 🔧 제공업체 추상 기본 클래스
│       ├── gemini.py                   # 🌐 Google Gemini API 클라이언트
│       ├── openai.py                   # 🚀 OpenAI 및 호환 API 클라이언트
│       └── anthropic.py                # 📖 Anthropic Claude API 클라이언트
├── utils/                              # 🛠️ 명령줄 도구
│   ├── api_crypto.py                   # 🔐 AES-GCM 암호화 핵심 구현
│   └── api_key_tool.py                 # 🗝️ API 키 관리 도구
├── test/                               # 🧪 테스트 모듈
│   └── test_core_workflow.py           # 🔧 주 워크플로우 테스트
└── openssl_dll/                        # 🔧 Windows PyInstaller OpenSSL 종속성
```

---

## 💡 문제 해결

- **번역을 시작할 수 없음**:
  - `config/models.yaml`에 최소한 하나의 암호화된 API 키가 구성되어 있는지 확인하세요.
  - 다른 프로그램이 전역 키보드 후크를 점유하고 있지 않은지 확인하세요.
- **번역 실패**:
  - 프로그램 시작 후 콘솔에서 옵션 `7`(API 상태 검사)을 선택하여 API 서비스의 가용성을 확인하세요.
  - `logs/app.log` 파일에서 자세한 오류 정보를 확인하세요.
- **권한 문제**:
  - 프로그램이 현재 디렉토리에 `config`, `logs`, `data` 폴더를 생성할 수 없는 경우, 사용자 홈 디렉토리(`C:/Users/YourUsername/.multitranslator`)에 자동으로 생성을 시도합니다. 이러한 위치 중 하나 이상이 쓰기 가능한지 확인하세요.

---

## 📄 라이선스

MIT License
