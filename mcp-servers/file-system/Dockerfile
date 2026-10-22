FROM docker.io/library/ubuntu:22.04
USER root

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
    && rm -rf /var/lib/apt/lists/*

# Python 심볼릭 링크 (root 권한으로 실행)
RUN ln -s /usr/bin/python3 /usr/bin/python

# 사용자 설정
ARG NB_USER=khdp-user
ARG NB_UID=1000
ARG NB_GID=100
RUN useradd -m -s /bin/bash -N -u $NB_UID $NB_USER

# 작업 디렉토리 생성 및 권한 설정
WORKDIR /app
RUN mkdir -p /app/data && chown -R $NB_USER:$NB_GID /app

# requirements 파일 복사 (권한 설정)
COPY --chown=$NB_USER:$NB_GID ./requirements.txt /app/requirements.txt

# 이제 사용자로 전환
USER $NB_USER

# Python 기본 설정 (사용자 권한으로)
RUN pip3 install --user --upgrade pip && pip3 install --user uv

# PATH 설정 (사용자 로컬 bin 추가)
ENV PATH="/home/$NB_USER/.local/bin:$PATH"

# requirements 설치 (사용자 권한으로)
RUN uv venv && uv pip install -r /app/requirements.txt
ENV PATH="/app/.venv/bin:$PATH"

# 앱 소스코드 복사 (compose 에서는 같은 경로에 소스를 :ro 로 덮어 마운트해 개발한다)
COPY --chown=$NB_USER:$NB_GID . /app/mcp-servers

WORKDIR /app/mcp-servers
ENTRYPOINT ["/bin/bash", "-c", "source /app/.venv/bin/activate && python /app/mcp-servers/main.py"]
