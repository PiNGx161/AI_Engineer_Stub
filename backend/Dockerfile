FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Copy dependency definition
COPY pyproject.toml ./

# Install dependencies (cached layer)
RUN uv sync --no-dev --no-install-project

# Copy application code
COPY . .

# Install the project itself
RUN uv sync --no-dev

EXPOSE 8000

RUN chmod +x start.sh

CMD ["bash", "start.sh"]
