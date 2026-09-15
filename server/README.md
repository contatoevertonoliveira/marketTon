# Affiliate Intelligence — backend (Fase 1)

Novo backend Django + DRF que implementa o núcleo do
`00 — Affiliate Intelligence System — Master Briefing.md`: catálogo de
produtos com proveniência, scoring versionado e explicável, máquina de
estados de portfólio e pipeline de criativos.

Convive com o stack legado (Streamlit em `dashboard/`, FastAPI em
`backend/main.py`) sem tocar nele — roda em porta e banco próprios.

## Rodando

```bash
server/.venv/Scripts/python.exe server/manage.py migrate
server/.venv/Scripts/python.exe server/manage.py seed_marketplaces
server/.venv/Scripts/python.exe server/manage.py runserver 8001
```

Admin em `http://127.0.0.1:8001/admin/` (crie um superuser com
`createsuperuser` para acessá-lo). API em `http://127.0.0.1:8001/api/`.

Frontend (novas telas "Daily Ops", "Portfólio" e "Integrações"):

```bash
npm --prefix frontend_app run dev
```

Ou via `.claude/launch.json` já configurado (`intelligence-backend` /
`intelligence-frontend`).

## Configurando credenciais de marketplace

Não usa `.env` — as credenciais ficam no banco, editáveis pela tela
**Integrações** do frontend (`http://localhost:5173`, item "Integrações" no
menu) ou via API (`PUT /api/marketplaces/{slug}/credentials/`). Cada
marketplace tem seu próprio esquema de campos, declarado em
`apps/catalog/credentials.py`:

- **Mercado Livre**: salve `client_id`/`client_secret`/`redirect_uri`, depois
  clique em "Conectar com Mercado Livre" para completar o OAuth (a API
  pública de busca exige `access_token` — confirmado ao vivo, retorna
  `403 forbidden` sem ele). Cadastre
  `http://127.0.0.1:8001/api/marketplaces/mercado_livre/oauth/callback/`
  como Redirect URI no app criado no painel de desenvolvedores da ML.
- **Shopee**: `app_id`/`secret` do Affiliate Open API
  (`open-api.affiliate.shopee.com/graphql`) — traz `commission_pct` e link
  de afiliado reais quando a API retorna a oferta.
- **Amazon**: `access_key`/`secret_key`/`associate_tag`/`host`/`region` da
  Product Advertising API 5.0. A conta de Associado só ganha acesso à API
  depois de 3 vendas qualificadas em 180 dias — sem isso, chaves corretas
  ainda assim são recusadas pela Amazon (não é bug daqui).

## Ingerindo produtos reais

```bash
server/.venv/Scripts/python.exe server/manage.py ingest_products --marketplace mercado_livre
server/.venv/Scripts/python.exe server/manage.py ingest_products --marketplace all
```

Sem credenciais configuradas, o comando avisa qual marketplace está sem
configuração e segue para o próximo — nunca inventa produto. TikTok
Shop/YouTube Shop ainda não têm adapter (`NotImplementedIngestion`).

## Testes

```bash
server/.venv/Scripts/python.exe server/manage.py test apps
```

Cobrem: o motor de scoring nunca fabrica dado ausente (pesos renormalizados,
reliability rebaixada), a máquina de estados de portfólio rejeita
transições inválidas, e o pipeline de criativos deriva `Publication: BLOCKED`
exatamente como no exemplo do briefing §8.

## O que falta (fora do escopo até agora)

Integração real TikTok Shop/YouTube Shop, Weekly Review automatizado,
Learning Engine com recalibração automática, Celery/Redis/scheduler,
autenticação/permissões, Docker, criptografia das credenciais em repouso
(hoje ficam em texto plano no SQLite local, mesma postura do resto do
projeto), e a decisão de aposentar o stack legado.
