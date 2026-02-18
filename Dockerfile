FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ARG SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0-dev
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SETUPTOOLS_SCM_PRETEND_VERSION}
COPY . .
RUN uv sync --frozen --no-dev --no-editable
RUN useradd -m appuser
USER appuser
EXPOSE 8080
CMD ["uv", "run", "python", "-m", "media_analyzer", "serve"]
