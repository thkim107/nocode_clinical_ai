FROM docker.io/library/ubuntu:22.04

# 환경 설정
ENV DEBIAN_FRONTEND=noninteractive

# 필수 패키지 설치 (Python, pip, C/C++ 컴파일러 등)
RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    build-essential \
    git \
    wget \
    curl \
    ca-certificates \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libreoffice \
    && rm -rf /var/lib/apt/lists/*

# Python 심볼릭 링크
RUN ln -s /usr/bin/python3 /usr/bin/python

# 작업 디렉토리 설정
WORKDIR /app

# requirements 설치
COPY ./requirements.txt /app/requirements.txt
RUN pip3 install --upgrade pip && pip3 install uv
RUN uv venv && uv pip install -r /app/requirements.txt
ENV PATH="/app/.venv/bin:$PATH"

# 데이터 디렉토리 생성
RUN mkdir -p /app/data

# 앱 소스코드 복사
COPY . /app/mcp-servers

# docx 파일 접근 허용 경로
ENV DOCX_BASE_DIR=/app/data

WORKDIR /app/mcp-servers
ENTRYPOINT ["/bin/bash", "-c", "source /app/.venv/bin/activate && python /app/mcp-servers/main.py"]
