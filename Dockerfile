FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/data HF_HOME=/data/model-cache OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
WORKDIR /app
RUN groupadd --gid 1001 app && useradd --uid 1001 --gid 1001 --no-create-home app
COPY pyproject.toml ./
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && python -c "import subprocess,tomllib; subprocess.check_call(['pip','install','--no-cache-dir',*tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']])"
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
COPY config ./config
COPY scripts/setup_db.py ./scripts/setup_db.py
RUN mkdir -p /data && chown 1001:1001 /data && ln -s /data /app/data
ARG SABER_BUILD_SHA=unknown
ENV SABER_BUILD_SHA=$SABER_BUILD_SHA
LABEL org.opencontainers.image.revision=$SABER_BUILD_SHA
USER 1001:1001
EXPOSE 8080
CMD ["python", "-m", "sabermetrics.server"]
