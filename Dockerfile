# A deployed GeoStats is a read-only publication. It serves the vintages
# committed in the repository and never reaches out to Geostat: refresh is a
# maintainer's action taken locally, whose output is a new immutable vintage to
# review and commit. GEOSTATS_ALLOW_REFRESH is therefore deliberately unset.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements first so a code change does not reinstall the dependency tree.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# The vintages ARE the data. Without them the image has nothing to serve, and
# the sqlite index is derived from them at build time rather than shipped:
# a committed database could disagree with the files it came from.
COPY data/vintages ./data/vintages

RUN python -m app.seed

# The app writes only the derived index and the fault lab's scratch copies.
RUN useradd --create-home --uid 10001 geostats \
    && chown -R geostats:geostats /app/data
USER geostats

EXPOSE 8013

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request;\
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8013/healthz').status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8013"]
