# marketTon Acquisition Playbook

Influencer badges: Lobos | Canali | Hybrid
Default: Hybrid Canali x Lobos

Meta: >= 1 venda por dia (baseline), objetivo máximo por dia sem teto artificial (R$ 97–297 ticket médio)
Objetivo macro: R$ 100k em 4 ciclos
Meta operacional: nunca menos de 1 venda/dia; dobrar vendas/dia sempre que o funil permitir

## Influencer Badges

- Canali
  - Quando usar: lançamento de produto nacional, ready stock, copy de valor (diferença vs concorrência).
  - Gatilhos: "pronta entrega", "fornecedor nacional", "case prático".
  - Canais: YouTube, Shopee/ML, anúncios Meta.

- Lobos
  - Quando usar: lançamento semanal, funil de intenção, copy direta, escala recorrente.
  - Gatilhos: "encerrando vagas", "12x de R$ 12", "case social".
  - Canais: Meta Ads, YouTube Shorts, TikTok lead.

- Hybrid (padrão)
  - Quando usar: ciclo geral semanal.
  - Combina: produto nacional + lançamento semanal.
  - Usar para testar a combinação dos dois estilos.

## Canais e métricas

- Google Trends
  - KPI: interesse por keyword ao longo do tempo.
  - Alerta: queda de busca = adiar copy.
- Meta Ads
  - KPI: CTR, CPC, CPL, ROAS.
  - Padrão alvo inicial: CTR >= 1.1%, CPC <= R$ 0,45, ROAS >= 2,8.
- Google Ads
  - KPI: impressões, taxa de conversão, CPA.
  - Padrão alvo inicial: CPA <= R$ 35, conv rate >= 3%.

## Agente mínimo viable para vender todo dia

1. Trend Hunter
   - Capta 1 trend por dia com Google Trends.
   - Se score baixo, filtra e retenta 1x/dia.

2. Product Hunter
   - Converte trend em 1 produto com ticket entre R$ 97 e R$ 297.
   - Prioriza estoque/pronta entrega.

3. Copy Chief
   - Gera 1 copy por dia no estilo Canali/Lobos conforme badge.
   - Usa headline direta e prova social.

4. Marketplace Manager
   - Publica 1 anúncio por dia com âncora de preço parcelado.
   - Roda 1 variant A/B por semana.

5. Growth Analyst
   - Mede métricas diárias por canal.
   - Se dia sem venda, sinaliza ajuste de copy/preço.

6. Master
   - Aprova ou bloqueia cada item.
   - Define badge do dia e garante >= 1 venda.
   - Remove bloqueios quando o funil estiver aquecido.

## Regra de afinação

- Se vendeu ontem: manter copy e canais.
- Se não vendeu em 2 dias: trocar copy + ajustar CPC/CPL.
- Se 3 dias sem venda: trocar produto (manter nicho).
- Registrar tudo em `memory/weekly_cycle_seed.json` e `data/app.sqlite3`.

## Regra de escala

- Se vendeu 2 dias seguidos: dobrar investimento em anúncios mantendo a copy vencedora.
- Se vendeu 3 dias seguidos: dobrar novamente até o ponto em que ROAS cair.
- Se vendeu 1 ou mais por dia por 7 dias: adicionar novo produto à esteira sem mudar o que já vende.
- Nunca reduzir anúncios quando houver vendas no dia anterior.
