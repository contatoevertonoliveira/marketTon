# Agente Claude no marketTon (MCP)

O marketTon tem um servidor MCP (`mcp_server/`) que dá ao Claude ferramentas para
consultar o sistema e, com o **modo agente** ligado, agir no portfólio de afiliação.

## Como funciona

```
Claude (Claude Code / Desktop)  ──MCP/stdio──▶  mcp_server  ──HTTP──▶  API do marketTon  ──▶  banco
                                   (ferramentas)            (login como usuário "agente")
```

- O servidor MCP **não fala com o banco nem com os marketplaces**. Ele chama a API do
  marketTon como um usuário de papel `bot` (o "agente"). Tudo passa pelas mesmas
  permissões e fica na **trilha de auditoria** (`Auditoria` → ações `agent.*`).
- O **modo agente** (interruptor no topo do app) é aplicado **na API**, não só na tela:
  - **Manual (padrão):** o agente só consulta. Qualquer escrita volta `403 modo agente desligado`.
  - **Ativo:** o agente pode executar as ações abaixo.
- Só um administrador liga/desliga. O agente não consegue se ligar sozinho nem se dar acesso.

## Conectar o Claude

1. No app, clique em **Conectar Claude** (topo) e em **Gerar acesso do agente**. O marketTon cria
   o usuário `claude_agent` com senha aleatória, mostrada **uma única vez**.
2. No PowerShell, na pasta do projeto, cole as três linhas que a tela mostra e rode `claude`:

   ```powershell
   $env:MARKETTON_API_URL="http://127.0.0.1:8000"
   $env:MARKETTON_AGENT_USER="claude_agent"
   $env:MARKETTON_AGENT_PASSWORD="<a senha mostrada>"
   claude
   ```

   O arquivo `.mcp.json` (na raiz do projeto) já declara o servidor; na primeira vez o Claude
   Code pede para aprovar. Para o Claude Desktop, adicione o mesmo bloco em
   `claude_desktop_config.json` com o caminho absoluto do Python do projeto.
3. A tela confirma sozinha quando o Claude conectar ("Claude conectado").

**Sobre "login pelo site do Claude":** o app não consegue autenticar você no Claude. O login do
Claude acontece no aplicativo do Claude (sua conta); o marketTon só precisa do acesso do agente,
que ele mesmo gera. **O agente só trabalha enquanto houver uma sessão do Claude aberta** — ele não
roda sozinho em segundo plano (para rotina diária, veja "Revisão diária").

## Ferramentas

**Consulta (sempre):** `marketton_status`, `marketton_checklist`, `list_products`, `get_product`,
`product_funnel`, `search_opportunities`, `trending_abroad`, `sales_performance`, `list_portfolio`,
`commission_proposals`, `daily_review`.

**Ação (só com o modo agente ligado):**

| Ferramenta | O que faz |
|---|---|
| `add_to_portfolio` | vincula um produto do catálogo ao portfólio |
| `move_portfolio_item` | muda o estado (afiliação pendente, afiliado, pausado, removido…) com motivo obrigatório |
| `set_manual_signals` | registra nº de afiliados e estoque que o usuário informou |
| `apply_observed_commissions` | preenche a comissão dos produtos sem taxa, usando o que as vendas mostraram |

## Comissão aprendida nas vendas

Produto sem comissão informada que já vendeu: a taxa efetiva é `Σ comissão / Σ valor vendido`
(confirmada vale mais que estimada; cancelada não conta). Regras:

- só preenche o que está **vazio** ou foi aprendido antes; **nunca** sobrescreve valor da API,
  da tabela do operador ou digitado;
- aparece a **confiança** (`baixa` com 1 venda, `media` 2–4, `alta` 5+) e a procedência
  (`attributes.commission_source = observed_from_sales`);
- roda ao final de `python scripts/ingest.py --sales` e sob demanda pela ferramenta.

## O que o agente NÃO tem (e por quê)

- **Credenciais, usuários, auditoria, publicação:** fora do papel `bot`, de propósito.
- **Editar anúncios/campanhas e listagens dos marketplaces:** a API do marketTon não expõe isso
  hoje. Afiliado não edita o anúncio do vendedor; e o Google Ads está conectado só para
  **Planejador de Palavras-chave** (leitura). Gerenciar campanhas exigiria escopo, permissão e
  telas próprias — não existe ainda.
- **Gerar links de afiliado e coletar o catálogo por HTTP:** a Shopee tem `generateShortLink`, mas
  falta o endpoint no marketTon; a coleta ainda é por `scripts/ingest.py`.
- **Cliques:** só chegam os que viraram compra; falta um encurtador com contagem.

## Revisão diária

`daily_review` entrega, em uma chamada, status, checklist, comissões aprendíveis e vendas por
marketplace. Para rodar todo dia, agende uma tarefa do Claude que chame essa ferramenta (o
marketTon e o backend precisam estar no ar naquele horário).

## Próximos passos (o que "vamos adicionando")

1. **Posicionamento orgânico por quem gasta em anúncio:** existe um coletor da Meta Ads Library
   (`collectors/meta_ads/`, `integrations/ads_meta/`) ainda sem endpoint nem credencial. Com
   `META_ACCESS_TOKEN`, vira ferramenta para listar anunciantes ativos por palavra-chave.
2. **Novos marketplaces (Hotmart, Kirvano, Monetizze…):** cada um precisa de um *adapter*
   (`integrations/marketplaces/`, interface `MarketplaceAdapter`) com credenciais e a API
   conferida contra uma conta real. Plugado o adapter, `daily_review` e as demais ferramentas passam
   a cobri-lo. Não foram escritos ainda para não inventar API que não foi validada.
3. Endpoint de coleta e de link de afiliado (acima).
