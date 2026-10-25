FROM ghcr.io/astral-sh/uv:0.13.5-python3.13-trixie-slim

WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
ENV PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

VOLUME /config
ENTRYPOINT ["chaoxing"]
CMD ["--config", "/config/config.toml"]
