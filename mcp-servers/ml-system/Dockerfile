FROM docker.io/library/ubuntu:22.04
USER root

# 환경 설정
ENV DEBIAN_FRONTEND=noninteractive

# 필수 패키지 설치 (Python, pip, C/C++ 컴파일러 등)
RUN apt-get update && apt-get dist-upgrade -y && apt-get install -y \
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
    sqlite3 \
    libsqlite3-dev \
    fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

# Python 심볼릭 링크 (root 권한으로 실행)
RUN ln -s /usr/bin/python3 /usr/bin/python

# 작업 디렉토리 설정
WORKDIR /app

# requirements 파일 복사
COPY ./requirements.txt /app/requirements.txt

# DB 디렉토리 생성
RUN mkdir -p /app/dbdata

# DB 초기화 스크립트 복사
COPY ./init_database.py /app/init_database.py

# Python 기본 설정
RUN pip3 install --upgrade pip && pip3 install uv

# requirements 설치
RUN uv venv && uv pip install -r /app/requirements.txt
ENV PATH="/app/.venv/bin:$PATH"

# entrypoint 스크립트 생성
RUN echo '#!/bin/bash' > /app/entrypoint.sh && \
    echo 'source /app/.venv/bin/activate' >> /app/entrypoint.sh && \
    echo '' >> /app/entrypoint.sh && \
    echo '# DB 파일이 없으면 초기화' >> /app/entrypoint.sh && \
    echo 'if [ ! -f /app/dbdata/your-database.db ]; then' >> /app/entrypoint.sh && \
    echo '    echo "Initializing database..."' >> /app/entrypoint.sh && \
    echo '    python /app/init_database.py' >> /app/entrypoint.sh && \
    echo 'fi' >> /app/entrypoint.sh && \
    echo '' >> /app/entrypoint.sh && \
    echo '# 메인 애플리케이션 실행' >> /app/entrypoint.sh && \
    echo 'cd /app/mcp-servers' >> /app/entrypoint.sh && \
    echo 'exec python main.py' >> /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

# 앱 소스코드 복사 (compose 에서는 같은 경로에 소스를 :ro 로 덮어 마운트해 개발한다)
COPY . /app/mcp-servers

WORKDIR /app/mcp-servers
ENTRYPOINT ["/app/entrypoint.sh"]