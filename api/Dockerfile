# 宮今 API (EC2 t4g = ARM 이라 linux/arm64 로도 빌드됨: docker buildx build --platform linux/arm64)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY vendor ./vendor
COPY data ./data

ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}

RUN useradd --create-home api
USER api

EXPOSE 8000
# LLM 대기 시간이 길어(3~20초) 워커 2개 + 워커마다 스레드풀로 동시 요청 처리
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
