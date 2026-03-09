FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set environment variables for uv
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install curl for nvm
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Configure and install nvm and node
ARG NODE_VERSION=20
ENV NODE_VERSION=${NODE_VERSION}
ENV NVM_DIR=/root/.nvm

RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install ${NODE_VERSION} \
    && nvm alias default ${NODE_VERSION} \
    && nvm use default \
    && ln -sf $(nvm which default) /usr/local/bin/node \
    && ln -sf $(dirname $(nvm which default))/npm /usr/local/bin/npm \
    && ln -sf $(dirname $(nvm which default))/npx /usr/local/bin/npx

# Set working directory
WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies without the project itself
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the project files
COPY . .

# Install the project
RUN uv sync --frozen --no-dev

# Expose the API port
EXPOSE 8000

# Start the server (uv run ensures it runs in the virtual environment)
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
