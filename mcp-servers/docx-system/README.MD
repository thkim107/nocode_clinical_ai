# Word Document MCP Server

## 개요

Word Document MCP Server는 Model Context Protocol(MCP) 기반의 Microsoft Word 문서(.docx) 조작 서버이다. Claude Desktop 등 MCP 호환 클라이언트와 연동하여, 프로그래밍 방식으로 Word 문서의 생성, 편집, 서식 적용, 보호, 변환 등 전반적인 문서 작업을 수행할 수 있도록 설계되었다.

서버는 FastMCP 프레임워크 위에 구축되어 있으며, Stateless HTTP 전송 방식으로 동작한다.

---

## 프로젝트 구조

```
docx-system/
├── main.py                              # 서버 실행 진입점
├── setup_mcp.py                         # MCP 구성 설정 스크립트
├── requirements.txt                     # Python 의존성 목록
├── docker-compose.yaml                  # Docker 서비스 구성
├── documents/
│   └── tripod_ai_system_prompt.txt      # TRIPOD+AI 가이드라인 문서
└── word_document_server/                # 핵심 서버 구현
    ├── main.py                          # FastMCP 서버 초기화 및 도구 등록
    ├── core/                            # 핵심 기능 모듈
    │   ├── styles.py                    # 스타일 및 서식 유틸리티
    │   ├── tables.py                    # 테이블 조작
    │   ├── protection.py                # 문서 보호 기능
    │   ├── footnotes.py                 # 각주/미주 처리
    │   └── unprotect.py                 # 문서 보호 해제
    ├── tools/                           # MCP 도구 정의
    │   ├── document_tools.py            # 문서 CRUD
    │   ├── content_tools.py             # 콘텐츠 추가 및 조작
    │   ├── format_tools.py              # 텍스트 및 테이블 서식
    │   ├── protection_tools.py          # 문서 보호 관련 도구
    │   ├── footnote_tools.py            # 각주/미주 도구
    │   ├── extended_document_tools.py   # 확장 문서 작업
    │   └── prompt_tools.py              # 가이드라인 조회 도구
    └── utils/                           # 유틸리티 함수
        ├── file_utils.py                # 파일 입출력 및 경로 안전성 검사
        ├── document_utils.py            # 문서 처리 유틸리티
        └── extended_document_utils.py   # 확장 문서 유틸리티
```

---

## 의존성

| 패키지 | 용도 |
|--------|------|
| `mcp[cli]` | Model Context Protocol 프레임워크 (CLI 포함) |
| `python-docx` | Word 문서(.docx) 생성 및 조작 |
| `msoffcrypto-tool` | Office 문서 암호화/복호화 |
| `docx2pdf` | Word 문서를 PDF로 변환 |

---

## 실행 방법

### 직접 실행

```bash
python main.py
```

서버는 `0.0.0.0`에서 Streamable HTTP 전송 방식으로 구동된다.

### Docker 실행

```bash
docker-compose up
```

- 컨테이너 내부 포트 8000이 호스트 포트 8004로 매핑된다.
- `./test-volume` 디렉터리가 컨테이너 내 `/app/data`로 마운트된다.
- 외부 Docker 네트워크 `snuhai`에 연결된다.

### MCP 구성 설정

```bash
python setup_mcp.py
```

Claude Desktop용 MCP 설정 파일을 자동 생성하며, 로컬 개발 환경, PyPI(UVX), Python 모듈 설치의 세 가지 배포 모드를 지원한다.

---

## 제공 도구 목록

### 문서 관리 (Document Tools)

| 도구 | 설명 |
|------|------|
| `create_document` | 새 Word 문서 생성 (제목, 작성자 지정) |
| `get_document_info` | 문서 메타데이터 조회 |
| `get_document_text` | 문서 전체 텍스트 추출 |
| `get_document_outline` | 문서 구조(목차 기반) 조회 |
| `list_available_documents` | 디렉터리 내 .docx 파일 목록 조회 |
| `copy_document` | 문서 복사 |

### 콘텐츠 편집 (Content Tools)

| 도구 | 설명 |
|------|------|
| `add_heading` | 제목 추가 (레벨 1~9) |
| `add_paragraph` | 단락 추가 |
| `add_table` | 테이블 생성 |
| `add_picture` | 이미지 삽입 |
| `add_page_break` | 페이지 구분선 삽입 |
| `delete_paragraph` | 단락 삭제 |
| `search_and_replace` | 텍스트 검색 및 치환 |

### 서식 적용 (Format Tools)

| 도구 | 설명 |
|------|------|
| `format_text` | 텍스트 범위 서식 지정 (굵기, 기울임, 밑줄, 색상, 크기, 글꼴) |
| `create_custom_style` | 사용자 정의 스타일 생성 |
| `format_table` | 테이블 서식 적용 (헤더, 테두리, 음영) |

### 문서 보호 (Protection Tools)

| 도구 | 설명 |
|------|------|
| `protect_document` | 비밀번호 기반 문서 암호화 |
| `unprotect_document` | 문서 보호 해제 |

### 각주/미주 (Footnote Tools)

| 도구 | 설명 |
|------|------|
| `add_footnote_to_document` | 각주 추가 |
| `add_endnote_to_document` | 미주 추가 |
| `customize_footnote_style` | 각주 스타일 변경 (번호 형식, 시작 번호, 글꼴, 크기) |

### 확장 기능 (Extended Document Tools)

| 도구 | 설명 |
|------|------|
| `get_paragraph_text_from_document` | 특정 인덱스의 단락 텍스트 조회 |
| `find_text_in_document` | 문서 내 텍스트 검색 (대소문자 구분, 전체 단어 매칭 옵션) |
| `convert_to_pdf` | Word 문서를 PDF로 변환 |

### 가이드라인 (Prompt Tools)

| 도구 | 설명 |
|------|------|
| `get_tripod_ai_guideline` | TRIPOD+AI 연구 보고서 작성 가이드라인 조회 |

---

## 아키텍처

### 모듈 간 의존 관계

```
main.py
  └── word_document_server/main.py (FastMCP 서버)
        └── Tools 등록
              ├── document_tools     ──> file_utils, document_utils
              ├── content_tools      ──> file_utils, core/styles
              ├── format_tools       ──> core/styles, core/tables
              ├── protection_tools   ──> core/protection, core/unprotect
              ├── footnote_tools     ──> core/footnotes
              ├── extended_document_tools ──> extended_document_utils
              └── prompt_tools       ──> documents/tripod_ai_system_prompt.txt
```

- **tools 계층**: MCP 프로토콜에 노출되는 도구 함수를 정의한다. 각 도구 함수는 입력 검증 후 core 또는 utils 모듈에 실제 처리를 위임한다.
- **core 계층**: 스타일, 테이블, 보호, 각주 등 문서 조작의 핵심 로직을 구현한다.
- **utils 계층**: 파일 경로 검증, 문서 텍스트 추출, 검색 등 공통 유틸리티를 제공한다.

### 보안 설계

- **경로 안전성**: `resolve_safe_path()` 함수를 통해 디렉터리 탈출(directory traversal) 공격을 방지한다.
- **쓰기 권한 검사**: 파일 수정 전 `check_file_writeable()` 함수로 권한을 사전 확인한다.
- **암호화**: `msoffcrypto` 라이브러리를 활용한 실제 Office 문서 암호화를 지원한다.
- **무결성 검증**: SHA256 해시 기반의 디지털 서명을 통해 문서 무결성을 확인할 수 있다.
- **오류 복구**: 암호화/복호화 실패 시 원본 파일 복원을 시도한다.

---

## 환경 변수

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `DOCX_BASE_DIR` | 문서 작업의 기준 디렉터리 | 현재 작업 디렉터리 |

Docker 환경에서는 `.env` 파일을 통해 추가 환경 변수를 설정할 수 있다.

---

## 참고 사항

- 서버는 Stateless HTTP 모드로 동작하므로, 요청 간 상태를 유지하지 않는다.
- `convert_to_pdf` 도구는 시스템에 LibreOffice 또는 Microsoft Word가 설치되어 있어야 정상 동작한다.
