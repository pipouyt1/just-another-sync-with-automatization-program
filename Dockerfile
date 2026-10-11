FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir aiohttp cryptography
COPY server.py index.html editor.html widget.js i18n.js agent.py ./
COPY hub.apk* HubSetup.exe* Dockerfile fly.toml VERSION CHANGELOG.md DESPLIEGUE.md ./
ENV PORT=8080 DB_PATH=/data/hub.db
CMD ["python", "server.py"]
