# Estado da migração — Affiliate Intelligence System

> Documento de trabalho. Reflete o que **existe no código verificado**, não o que está
> planejado. Última verificação: **344 testes passando** (3 execuções seguidas, 20s),
> 34 tabelas, 55 rotas de negócio, reversibilidade completa de `head` a `base`.

## Decisões tomadas

| Decisão | Escolha |
|---|---|
| Banco de dados | PostgreSQL 16 (Docker Compose) |
| Frontend | React (Streamlit em aposentadoria) |
| Agentes | Componentes de IA real — IA interpreta, não calcula score |
| Dados antigos | Descartados — começamos limpos |
| Marca | `marketTon` continua como nome do produto |
| Marketplaces | APIs oficiais: Mercado Livre, Shopee, Amazon, TikTok Shop |

---

## Fases 0 a 4 + autenticação — concluídas

### Fase 0 — desbloqueio
O defeito central: `start()` do orquestrador nunca alimentava a fila, então **nenhum
agente jamais havia executado** por esse caminho.

### Fase 1 — modelo de domínio
Motor de scoring com 4 dimensões explicáveis; máquina de estados do portfólio com
portão de publicação; proveniência obrigatória por constraint.

### Fase 2 — conectores e ingestão
Os quatro marketplaces, cada um declarando o que devolve e o que não.

### Fase 3 — camada de IA
Seis prompts versionados. Toda saída gravada em `ai_interpretations` com modelo,
versão de prompt, insumos exatos e resposta bruta. `growth_analyst` convertido.

### Fase 4 — API
55 rotas cobrindo catálogo, scoring, portfólio, criativos, jobs e operação.
Os endpoints de suporte saíram do `sqlite3` bruto para modelos SQLAlchemy.

### Autenticação — o bloqueador da rodada anterior, fechado

Antes: **49 rotas sem nenhuma autenticação.** `PUT /support/preferences/{user_id}`
deixava qualquer um sobrescrever preferências de outro usuário; `GET /support/feedback`
expunha ids e nomes; e `core/db.py` declarava `password TEXT NOT NULL` — senha em
texto puro, sem nenhuma dependência de hashing no projeto.

Agora:

| Peça | O que garante |
|---|---|
| Argon2 via `pwdlib` | Resistente a GPU por ser memory-hard; custo configurável |
| Access token JWT curto | 12h, com `jti` para revogação pontual |
| Refresh token com estado | Guardado **como hash**; rotação a cada uso; permite logout real |
| Bloqueio após 5 falhas | Sem isso, força bruta dependeria da boa vontade do atacante |
| Revalidação no banco | Papel alterado ou conta desativada cortam o acesso imediatamente |
| `audit_log` | Quem fez, quando, com qual papel e qual resultado |
| 22 permissões × 5 papéis | Aplicadas por `Depends(require(...))` na API, não no frontend |

**Três decisões de projeto que valem registro:**

**Revalidar contra o banco a cada requisição.** Um JWT puro carrega o papel e não pode
ser revogado. Se confiássemos só nele, um usuário rebaixado manteria privilégio de
manager por até 12 horas. O custo é uma consulta por requisição; o benefício é que o
corte é imediato. Há teste para os dois casos (rebaixamento e desativação).

**Rotação de refresh token.** Um refresh reutilizável indefinidamente é um segredo de
longa duração. Emitindo um novo e revogando o anterior, a janela de exploração de um
vazamento fica limitada ao intervalo entre usos.

**Aprovar criativo exige permissão separada.** `creatives.edit` deixa mover status;
`creatives.approve` libera publicação. O portão do briefing §8 depende da aprovação, e
quem edita material não deve necessariamente poder liberá-lo. A checagem é no endpoint,
não no router, porque só o alvo `APPROVED` exige a permissão extra.

**Trava contra auto-bloqueio:** um admin não pode rebaixar nem desativar a própria
conta. Sem isso, ele se tranca fora e não há caminho de volta.

---

## Verificação executada

```
$ pytest tests/ -q      (3 execuções, sem flakiness)
344 passed em 20s

$ alembic upgrade head --sql
34 CREATE TABLE, 133 CREATE INDEX

$ downgrade head → base
3 + 6 + 1 + 24 = 34 DROP TABLE   (reversibilidade completa)

$ ast.parse em 132 arquivos .py
0 erros de sintaxe
```

| Arquivo de teste | Testes | Foco |
|---|---|---|
| `test_api_auth.py` | 66 | A API **recusa** anônimo e papel sem permissão; rotação de refresh; auditoria |
| `test_auth.py` | 58 | Hashing, JWT, bloqueio por tentativas, revogação, matriz de permissões |
| `test_api.py` | 47 | Explicabilidade por HTTP; 409 com transições permitidas; portão de publicação |
| `test_scoring.py` | 43 | Soma das contribuições reconstrói o score |
| `test_connectors.py` | 29 | Assinatura HMAC/SigV4; falha explícita sem credencial |
| `test_ingestion.py` | 22 | Proveniência obrigatória; idempotência |
| `test_portfolio.py` | 20 | Grafo de transições; portão de publicação |
| `test_schema.py` | 18 | Migration ↔ ORM; cadeia linear; reversibilidade |
| `test_ai_layer.py` | 17 | IA não é dependência; saída auditável |
| `test_growth_analyst.py` | 14 | KPIs determinísticos; comissão estimada ≠ realizada |
| `test_orchestrator.py` | 14 | Fila alimentada; pausa não descarta trabalho |

### Bugs que os testes encontraram nesta rodada

- **`jobs`, `operations` e `support` estavam sem nenhuma proteção.** Não fossem os
  testes de "anônimo recebe 401", três famílias inteiras de rotas teriam ficado
  abertas — incluindo `GET /support/feedback`, que expõe dados de usuários. Este é
  exatamente o tipo de buraco que só um teste que faz a requisição HTTP pega.
- **`test_api.py` dependia de `AUTH_ENABLED=false`** e quebrava quando
  `test_api_auth.py` ligava auth no import — o ambiente vaza entre módulos de teste.
  A correção foi tornar o cliente de teste **autenticado de verdade**, com login real,
  em vez de anônimo por atalho. Testa o caminho de produção.
- **`Optional` é obrigatório na anotação de dependência com default `None`.** Sem ele
  o FastAPI interpreta o `None` como dependência e falha na montagem da rota.
- **Argon2 a custo de produção levava a suíte a 63s.** O custo agora é configurável:
  padrão RFC 9106 em produção, reduzido em teste. 63s → 20s.

---

## Ambiente

A `.venv` original foi criada em outra máquina Linux e é lixo. Recriada com
`uv venv .venv --python 3.11`.

**PostgreSQL nunca foi conectado.** Não há Docker neste ambiente. A validação do
schema é por geração de DDL offline, reversibilidade por revision e comparação
estrutural com os modelos — não por conexão real.

### Antes de subir

```bash
cp .env.example .env
python scripts/generate_jwt_secret.py --write   # substitui o segredo de dev
# defina BOOTSTRAP_ADMIN_USERNAME e BOOTSTRAP_ADMIN_PASSWORD para criar o admin inicial
docker compose up -d db redis
alembic upgrade head
uvicorn backend.main:app --reload --port 8000
```

`GET /health` reporta `production_blockers`: a lista do que ainda impede produção.
Hoje ela inclui o segredo de desenvolvimento e o SQLite dos testes.

---

## O que falta

### Fase 3 (continuação)
5 dos 6 agentes ainda são determinísticos (`trend_hunter`, `product_hunter`,
`copy_chief`, `marketplace_manager`, `master`). O orquestrador não grava em
`jobs`/`job_events`.

### Fase 5 — frontend
React sem router, sem API client, sem TypeScript, sem gráficos. O React atual chama
7 endpoints que não existem nas 55 rotas. **Precisa ser reescrito contra a API real**,
agora incluindo a tela de login e o fluxo de refresh.

### Fase 6 — automação
Celery + Redis não ligados; scheduler do ciclo não existe.

### Decisão pendente
As 19 páginas Streamlit e `dashboard/app.py` (`np.random`) continuam no repositório.
`core/roles.py` mantém um `RoleManager` como shim para não deixá-las quebrar. Remover
ou mover para `legacy/` segue sem resposta.
