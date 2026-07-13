# PlayMCP in KC (Git 소스 빌드) / Oracle Cloud 등 컨테이너 배포용.
# KC 요건: 저장소 루트의 Dockerfile, 컨테이너가 8000 포트에서 listen (container_port 기본값).
# ⚠️ ENV PORT=8000 이 반드시 필요 — main.py는 PORT가 있어야 Streamable HTTP 모드로 뜬다
#    (없으면 stdio 모드 → 포트를 열지 않아 헬스체크 실패 = lolgpt가 KC에서 failed 났던 원인)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY data/ data/

ENV PORT=8000
EXPOSE 8000

CMD ["python", "main.py"]
