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

## Em segundo plano, sem terminal (padrão)

Com o **modo agente ligado**, o próprio **backend** executa o Claude Code em modo sem tela (`claude -p`)
quando há trabalho. Não precisa deixar terminal aberto:

| Gatilho | Quando |
|---|---|
| ativação | há uma tarefa de ativação aberta (ao ligar o modo) |
| chat | você escreveu e o agente ainda não leu (intervalo mínimo de 5 min) |
| manhã / noite | rotinas diárias, **só em autonomia independente**, a partir das 8h e das 19h (`AGENT_MORNING_HOUR`, `AGENT_EVENING_HOUR`), uma por período |
| manual | botão **Rodar agora** (administrador) |

- **Login uma única vez:** abra um terminal, rode `claude` e use `/login`. Fica salvo na sua conta do Windows.
  Se expirar, a rodada falha com um sinal claro: o chat recebe um pedido ("Entrar no Claude Code"), as tentativas
  pausam por 15 min e voltam sozinhas.
- **Isolamento:** a rodada carrega **só** o servidor do marketTon (`--strict-mcp-config`), com lista fechada de
  ferramentas; terminal, leitura/edição de arquivos e web ficam **proibidos**; o processo filho não herda as
  variáveis do backend e recebe um token de sessão emitido pelo backend (nenhuma senha guardada).
- **Uma rodada por vez**, com tempo máximo (`AGENT_RUN_TIMEOUT_MINUTES`, 25). Cada rodada fica registrada
  (painel "Agente em segundo plano" no chat: estado, últimas rodadas e saída).
- **Requisitos:** o computador ligado, o Docker e o backend no ar, e o Claude Code instalado e logado.
  Cada rodada consome o uso da sua conta do Claude.
- **Desligar:** o interruptor do topo (modo manual), ou `AGENT_AUTORUN=false` no `.env` para o backend nunca
  disparar o Claude.

## Usar o agente num terminal (opcional)

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

## Links rastreados (contador de cliques)

O redirecionador roda no **seu domínio público** (funções Netlify em `site/netlify/functions`), porque o backend
fica no `localhost`, que a internet não alcança. `create_tracked_link(item, canal, campanha)` gera
`felixsystems.com.br/r/<código>`, que redireciona ao **link de afiliado** do produto e conta o clique; `sync_clicks`
traz as contagens para o banco (alimenta Produtos → Desempenho → "Mais cliques"). Cliques são contados mesmo com o
computador desligado.

- **Só encurta link de afiliado** (o comum daria clique sem comissão). Mesmo produto + canal + campanha reaproveita o link.
- **Contagem honesta:** robôs e pré-visualizadores (WhatsApp, Telegram, Facebook…) não contam; clique não é
  visualização do post nem venda. Por clique guarda só data/hora, país aproximado, tipo de dispositivo e site de origem
  — **sem IP e sem cookie** (a política de privacidade do site já diz isso).
- **Configuração:** Integrações → Encurtador de links (endereço + token). O token fica só aqui; o redirecionador guarda
  apenas o **hash** dele. Para trocar: gere outro token, troque `TOKEN_SHA256` em `links-admin.mjs` e publique de novo.

## Atualização do catálogo

`refresh_catalog` roda a coleta (como `scripts/ingest.py`) em segundo plano, com `keywords` opcionais (até 10). Uma por
vez, intervalo mínimo de 6 h por marketplace, o agente não força; o resultado cai no chat (`catalog_refresh_status`).

## O que o agente NÃO tem (e por quê)

- **Credenciais, usuários, auditoria, publicação:** fora do papel `bot`, de propósito.
- **Editar anúncios/campanhas e listagens dos marketplaces:** a API do marketTon não expõe isso
  hoje. Afiliado não edita o anúncio do vendedor; e o Google Ads está conectado só para
  **Planejador de Palavras-chave** (leitura). Gerenciar campanhas exigiria escopo, permissão e
  telas próprias — não existe ainda.
- **Gerar o link de afiliado na Shopee:** a API tem `generateShortLink`, mas falta o endpoint no marketTon (hoje o
  link vem do catálogo).

## Revisão diária

`daily_review` entrega, em uma chamada, status, checklist, comissões aprendíveis e vendas por
marketplace. Para rodar todo dia, agende uma tarefa do Claude que chame essa ferramenta (o
marketTon e o backend precisam estar no ar naquele horário).

## Próximos passos (o que "vamos adicionando")

1. **Posicionamento orgânico por quem gasta em anúncio:** existe um coletor da Meta Ads Library
   (`collectors/meta_ads/`, `integrations/ads_meta/`) ainda sem endpoint nem credencial. Com
   `META_ACCESS_TOKEN`, vira ferramenta para listar anunciantes ativos por palavra-chave.
2. **Plataformas digitais:** Hotmart, Monetizze e Eduzz já têm adaptador e card em Integrações (veja
   `docs/plataformas-digitais.md`; autenticação conforme a documentação oficial, formato das vendas ainda
   sem validação em conta real). **Kirvano** segue pendente: precisa de adaptador e da documentação oficial.
3. Endpoint de coleta e de link de afiliado (acima).
