FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src
WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.txt

COPY src ./src
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "perry.app:app", "--host", "0.0.0.0", "--port", "8000"]
