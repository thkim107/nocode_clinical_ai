# Stage 1: build the React frontend
FROM docker.io/library/node:20-alpine AS frontend
# 서브패스 배포 시 --build-arg BASE_PATH=/apps/research-agent (vite base). 기본 "/" = compose/로컬.
ARG BASE_PATH=/
ENV BASE_PATH=$BASE_PATH
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend serving the API and the built frontend
FROM docker.io/library/python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
# 빌드 컨텍스트 shared=<repo>/shared (compose additional_contexts / podman --build-context)
COPY --from=shared audit_logger.py /app/audit_logger.py
COPY --from=frontend /build/dist /app/static

# /app/data  : shared volume (volume_storage), browsed by the Files tab
# /app/state : platform-private state (research session store)
RUN mkdir -p /app/state
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
