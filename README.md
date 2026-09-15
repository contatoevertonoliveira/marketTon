# marketTon — Affiliate Intelligence System

Plataforma de inteligência e operação para marketing de afiliados multi-marketplace.
Descobre oportunidades, analisa produtos, prioriza o que tem maior potencial, controla
a produção de criativos, acompanha publicações e vendas e aprende com os resultados reais.

> Especificação de referência: *Affiliate Intelligence System — Master Briefing V2*.
> Estado da migração: `PROJECT_STATUS.md`.

## Stack

| Camada | Tecnologia |
|---|---|
| Banco | PostgreSQL 16 |
| API | Python 3.11+, FastAPI, SQLAlchemy 2.0, Alembic |
| Fila / cache | Redis 7 |
| Frontend | React 18 + Vite (em `frontend_app/`) |
| Infra local | Docker Compose |

O domínio depende de concorrência real entre API e workers e de tipos que o SQLite
não oferece. Por isso `config/settings.py` **recusa** qualquer `DATABASE_URL` que não
seja PostgreSQL, exceto em testes (`ALLOW_SQLITE=true`). Manter SQLite em
desenvolvimento foi o que produziu, no projeto anterior, três definições
incompatíveis das mesmas tabelas.

## Como rodar

### 1. Infraestrutura

```bash
cp .env.example .env
docker compose up -d db redis
```

### 2. Dependências

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# alternativa mais rápida, se você usa uv:
# uv pip install -r requirements.txt
```

### 3. Banco de dados

```bash
alembic upgrade head
```

As migrations são a **única** fonte de verdade do schema. Não existe mais
`backend/schema.sql` (que era referenciado aqui e nunca existiu) nem criação de
tabelas em tempo de execução. Para reverter: `alembic downgrade base`.

### 4. API

```bash
uvicorn backend.main:app --reload --port 8000
```

Documentação interativa: <http://localhost:8000/docs>

### 5. Frontend

```bash
cd frontend_app
npm install
npm run dev
```

Abra <http://localhost:5173>. Essa porta é a origem liberada por padrão em
`CORS_ORIGINS`; usar outra exige ajustar o `.env`.

## Testes

```bash
pytest              # ou: pytest tests/ -v
ruff check .        # lint
```

Os testes rodam em SQLite em memória por velocidade, exercitando o mesmo schema.
Eles cobrem a coerência entre os modelos ORM e a migration, o motor de scoring e a
máquina de estados do portfólio.

## Estrutura

```
alembic/                  Migrations (fonte de verdade do schema)
backend/main.py           Aplicação FastAPI
config/settings.py        Configuração validada de variáveis de ambiente
core/db/                  Modelos SQLAlchemy
core/services/            Regras de negócio: scoring, portfólio
core/orchestrator.py      Execução do pipeline de agentes
integrations/             Adapters de marketplace e APIs externas
collectors/               Coleta de dados (Google Trends, Meta Ads)
agents/                   Agentes do pipeline operacional
frontend_app/             Frontend React
data/                     Persistência local e artefatos de execução
memory/                   Estado do orquestrador (artefato de execução)
dashboard/                Streamlit — legado, em processo de aposentadoria
```

## Decisões de arquitetura

Três regras que o código aplica ativamente, não apenas documenta:

**Proveniência obrigatória.** Nada entra no domínio sem um registro em
`source_records`. `products.source_record_id` é `NOT NULL` com `ON DELETE RESTRICT`.
Um produto sem origem declarada é um erro de schema, não um caso de borda.

**Ausência não é zero.** Todo campo de mercado é anulável, e o motor de scoring
distingue "não sabemos" de "é ruim": um fator sem dado sai do denominador e reduz a
`confidence` em vez de contribuir com zero. O briefing proíbe estimativa silenciosa —
e 0 é uma estimativa.

**A explicação é a aritmética.** O `score` de um produto é a soma dos `impact` de suas
`score_contributions`. Não existe uma narrativa gerada à parte do cálculo: a resposta
a "por que este produto foi recomendado?" é o próprio cálculo, persistido com inputs,
pesos, fórmula e versão.

## Convenções

- Backend sempre na porta 8000; frontend na 5173.
- Nenhuma regra de negócio no frontend: scores, estados e permissões vivem no backend.
- Não commitar `.env` nem artefatos de execução (`data/reports/`, `memory/state.json`).
- Alterar pesos ou fórmula de um score exige publicar uma **nova versão** do algoritmo
  em `score_algorithms`. Versões são imutáveis para que o histórico continue comparável.
