FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY atlas ./atlas
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home atlas
USER atlas
CMD ["uvicorn", "atlas.api:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
