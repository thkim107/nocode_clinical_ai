# DB-Connector: Clinical Database MCP Service

## 개요

DB-Connector는 Model Context Protocol(MCP) 기반의 임상 데이터베이스 통합 조회 서비스이다. 다수의 PostgreSQL 임상 데이터베이스에 대해 단일 인터페이스를 통한 SQL 질의, 스키마 탐색, CSV 내보내기 기능을 제공한다. LLM과 연동하여 사용자가 자연어로 임상 데이터를 탐색할 수 있도록 설계되었다.

## 지원 데이터베이스

| 데이터베이스 | 설명 | 스키마 |
|---|---|---|
| **CDM** | OMOP Common Data Model v5.3 (HIRA) | 단일 스키마 |
| **KMIMIC** | Korean MIMIC, 다기관 중환자실 데이터 | km001, km006, km012 |
| **MIMIC-IV** | MIMIC-IV 임상 데이터 | mimiciv_hosp, mimiciv_icu |

## 프로젝트 구조

```
db-connector/
├── main.py                        # MCP 서버 진입점
├── requirements.txt               # Python 의존성
├── Dockerfile                     # 컨테이너 빌드 설정
├── docker-compose.yaml            # Docker Compose 배포 설정
├── .env.example                   # 환경 변수 템플릿
│
├── config/
│   └── databases.yaml             # 데이터베이스 레지스트리 설정
│
├── core/                          # 핵심 모듈
│   ├── database_registry.py       # 데이터베이스 설정 싱글톤 레지스트리
│   ├── base_database.py           # 어댑터 추상 기반 클래스
│   ├── query_executor.py          # SQL 실행 엔진
│   └── metadata_manager.py        # JSON 메타데이터 로딩 및 조회
│
├── adapters/                      # 데이터베이스별 어댑터
│   ├── cdm_adapter.py             # OMOP CDM 어댑터 (HIRA 개념 매핑 포함)
│   ├── kmimic_adapter.py          # Korean MIMIC 어댑터
│   └── mimiciv_adapter.py         # MIMIC-IV 어댑터
│
├── tools/                         # MCP 도구 등록
│   ├── query_tools.py             # SQL 질의 도구
│   ├── metadata_tools.py          # 스키마 메타데이터 도구
│   └── job_tools.py               # 작업 상태 추적 도구
│
├── export/                        # CSV 내보내기
│   ├── csv_exporter.py            # 스트리밍 CSV 내보내기 (배치 처리)
│   └── job_status_manager.py      # SQLite 기반 작업 상태 관리
│
├── utils/                         # 유틸리티
│   ├── path_validator.py          # 파일 경로 보안 검증
│   └── init_database.py           # SQLite 초기화
│
└── documents/                     # 메타데이터 문서
    ├── cdm/                       # CDM 스키마 정보, HIRA 개념 매핑
    ├── kmimic/                    # KMIMIC 스키마 정보
    ├── mimiciv/                   # MIMIC-IV 스키마 정보
    └── guides/                    # 연구 가이드 (코호트, 통계, 시각화)
```

## 아키텍처

### 핵심 설계 원칙

- **싱글톤 패턴**: `DatabaseRegistry`가 YAML 설정을 단일 인스턴스로 관리하며, 환경 변수에서 접속 URL을 해석한다.
- **팩토리 패턴**: `get_adapter()` 함수가 데이터베이스 ID에 따라 적절한 어댑터 인스턴스를 반환한다.
- **추상 기반 클래스**: `BaseDatabaseAdapter`가 모든 어댑터의 공통 인터페이스를 정의한다.
- **메타데이터 캐싱**: `MetadataManager`가 JSON 메타데이터를 로딩 후 캐싱하여 반복 조회 성능을 확보한다.

### 데이터 흐름

```
LLM  -->  MCP Tools (tools/)  -->  Core 모듈 (core/)
                                            ├── QueryExecutor  -->  PostgreSQL
                                            ├── MetadataManager  -->  JSON 문서
                                            └── Adapters (adapters/)  -->  DB별 로직
```

### 모듈 상세

#### core/

| 파일 | 역할 |
|---|---|
| `database_registry.py` | `databases.yaml`에서 DB 설정 로딩, 접속 URL 해석, 스키마 유효성 검증 |
| `base_database.py` | 어댑터 추상 클래스. 개념 매핑, 가이드 조회 등의 인터페이스 정의 |
| `query_executor.py` | PostgreSQL 대상 SQL 실행, 결과 포맷팅, CSV 배치 처리 지원 |
| `metadata_manager.py` | JSON 메타데이터 로딩 및 캐싱. 테이블, 필드, 키, 관계 정보 조회 |

#### adapters/

| 파일 | 역할 |
|---|---|
| `cdm_adapter.py` | OMOP CDM 전용 기능. HIRA 개념 ID-이름 매핑, 연구 가이드 제공 |
| `kmimic_adapter.py` | 다기관 스키마(km001, km006, km012) 통합 처리 |
| `mimiciv_adapter.py` | mimiciv_hosp, mimiciv_icu 이중 스키마 지원 |

#### export/

| 파일 | 역할 |
|---|---|
| `csv_exporter.py` | 메모리 효율적인 배치 스트리밍 CSV 내보내기. 파일 크기 초과 시 자동 분할 |
| `job_status_manager.py` | 스레드 안전한 SQLite 기반 비동기 작업 추적. 진행률, 오류 상태 관리 |

## MCP 도구 목록

### SQL 질의

- `query(db, sql, parameters)`: SQL 질의 실행 후 결과 반환 (기본 5행 제한)
- `query_to_csv(db, sql, path, parameters, batch_size, max_file_size_mb)`: 비동기 CSV 내보내기 (작업 추적 포함)

### 메타데이터 탐색

- `get_names(db, mode, schema_name)`: 테이블 또는 필드 이름 목록 조회
- `get_keys(db, schema_name, table_name)`: 기본 키 및 외래 키 정보 조회
- `get_relations(db, schema_name)`: 전체 외래 키 관계 조회
- `get_descriptions(db, level, schema_name, table_name)`: 스키마/테이블/필드 수준 설명 조회
- `concept_id_to_name(concept_ids)`: HIRA 개념 ID를 이름으로 변환 (CDM 전용)
- `get_research_guide(guide_type)`: 연구 가이드 조회 (코호트 정의, 통계 분석, 시각화)

### 작업 관리

- `get_job_status(job_id)`: 비동기 작업 상태 조회
- `get_latest_jobs(n)`: 최근 N개 작업 상태 조회

### 서버 정보

- `list_databases()`: 사용 가능한 데이터베이스 목록 및 기능, 스키마 정보 조회

## 설정

### 환경 변수

| 변수 | 설명 |
|---|---|
| `DB_CONFIG_PATH` | `databases.yaml` 파일 경로 |
| `METADATA_BASE_PATH` | `documents/` 디렉토리 경로 |
| `CDM_DATABASE_URL` | CDM PostgreSQL 접속 URL |
| `KMIMIC_DATABASE_URL` | KMIMIC PostgreSQL 접속 URL |
| `MIMICIV_DATABASE_URL` | MIMIC-IV PostgreSQL 접속 URL |

### databases.yaml 주요 설정

- `default_batch_size`: CSV 내보내기 배치 크기 (기본 10,000행)
- `max_file_size_mb`: CSV 파일 최대 크기 (기본 1,024MB)
- `job_status_db_path`: 작업 상태 SQLite DB 경로
- `default_query_limit`: 기본 질의 결과 행 수 제한 (기본 5행)

## 실행 방법

### Docker Compose

```bash
docker compose up -d
```

서비스는 포트 8005(호스트) -> 8000(컨테이너)으로 매핑되며, `snuhai` 외부 네트워크에 연결된다.

### 직접 실행

```bash
pip install -r requirements.txt
python main.py
```

서버는 Streamable HTTP 트랜스포트로 기동된다.

## 의존성

| 패키지 | 버전 | 용도 |
|---|---|---|
| `mcp` | >= 1.0.0 | MCP 서버 프레임워크 (FastMCP) |
| `psycopg2-binary` | >= 2.9.0 | PostgreSQL 드라이버 |
| `pyyaml` | >= 6.0 | YAML 설정 파싱 |

런타임 환경: Python 3.11

## 보안

- 데이터베이스 접속 정보는 환경 변수를 통해 주입
- SQLite 접근 시 스레드 안전 잠금 적용
