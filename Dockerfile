# marketTon API (produção). Também traz o Claude Code, que o agente em segundo plano chama pelo supervisor.
# O login do Claude Code é feito uma vez dentro do contêiner e fica no volume do /home/app.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates tzdata bash \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

USER app
# Claude Code: instalador oficial da Anthropic (instala em ~/.local/bin).
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/home/app/.local/bin:${PATH}"

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
