# Hotmart, Monetizze e Eduzz no marketTon

Plataformas de produtos digitais. Entram em **Integrações** como cards (um por plataforma), no
mesmo fluxo dos marketplaces: preencher as credenciais, **Salvar**, **Testar conexão**.

A documentação oficial de cada uma foi lida em 21/10/2026 e o código segue o que ela descreve.
O endereço de cada página está no topo de `integrations/marketplaces/digital_platforms.py`.

## Onde pegar as credenciais

| Plataforma | Campos no card | Onde gerar |
|---|---|---|
| **Hotmart** | Client ID · Client Secret · Token Basic · Ambiente de testes | Hotmart → **Ferramentas → Credenciais de desenvolvedor → Criar credencial** (gera os três valores). Para testar sem dados reais, crie uma credencial marcada **sandbox** e escreva `sim` no campo de ambiente. |
| **Monetizze** | Chave de API (consumer key) | Monetizze → **Ferramentas → API → Nova chave de API**. |
| **Eduzz** | Client ID · Client Secret | **console.eduzz.com → Aplicativos** (criar um aplicativo; as credenciais saem da tela de gerenciamento). |

## O que cada uma entrega

| | Hotmart | Monetizze | Eduzz |
|---|---|---|---|
| Autenticação | OAuth2 `client_credentials` + header `Basic`; token dura ~48 h | `GET /2.1/token` com `X_CONSUMER_KEY`; token de 15 min que renova a cada uso | OAuth2 `client_credentials` em `accounts-api.eduzz.com`; um token ativo por vez |
| Vendas como afiliado | sim (`/sales/history`, `commission_as=AFFILIATE`) | sim (`/transactions`) | sim (`/myeduzz/v1/sales`) |
| Comissão | sim, por transação (`/sales/commissions`, fonte `AFFILIATE`) | sim, lista `comissoes` | usa `netGain` da venda |
| Produtos para afiliar | **não** (API lista só os do produtor) | sim: `/myproducts` (os que você já afilia) | **não** (API lista só os do produtor) |

Por isso, na Hotmart e na Eduzz os produtos aparecem **pelas vendas** (Produtos → Desempenho), não
no catálogo de sugeridos. Comissão por venda alimenta a taxa observada do sistema.

## Status das comissões

* **Hotmart:** `APPROVED` = paga, ainda na garantia → comissão **estimada**; `COMPLETE` = garantia
  encerrada → **confirmada**. Cancelada, reembolsada e chargeback viram `CANCELLED`, sem comissão.
* **Monetizze:** `Completa` → confirmada; `Finalizada` → estimada; `Aguardando pagamento` → sem
  comissão; `Cancelada`/`Devolvida`/`Bloqueada` → cancelada.
* **Eduzz:** status `paid` etc. → confirmada; pendente → estimada; reembolsada/cancelada → cancelada.

## O que NÃO está validado (honestidade)

O fluxo de **autenticação** segue a documentação à risca. Já o **formato exato das respostas de venda**
foi montado pelos exemplos da documentação e **não foi testado com conta real**:

* **Monetizze:** a doc não diz qual item de `comissoes` é o do afiliado que consulta. Só se aceita
  quando há um candidato único (item com `refAfiliado`, ou lista de 1); com mais de um, a comissão fica
  vazia em vez de chute. A data usada é `dataInicio` (a doc não traz a data da compra de forma clara).
* **Eduzz:** os valores do campo `status` e o significado de `netGain` para a conta de afiliado não são
  detalhados; os parâmetros `referenceDate` e o formato de `startDate` da listagem também não. Se a API
  recusar, o erro aparece no card ao testar/coletar.
* **Hotmart:** o limite de requisições não foi consultado; um HTTP 429 aparece como erro legível.

Na primeira coleta com conta real, se algum campo vier diferente, o ajuste é pontual (como foi na
Shopee). Dados de **teste de conexão** e **sandbox** da Hotmart não afetam a conta real.

## Como coletar

```bash
python scripts/ingest.py --marketplace hotmart --sales
python scripts/ingest.py --marketplace monetizze --sales
python scripts/ingest.py --marketplace eduzz --sales
python scripts/ingest.py --marketplace monetizze          # catálogo (só a Monetizze lista produtos)
```

Ou pelo agente: `sync_sales` traz as vendas de todas as plataformas configuradas, aprende comissão e
avisa cada venda nova no chat.

## Kirvano

Ainda não tem adaptador: a documentação oficial não foi consultada. Fica como pendência na lista de
capacidades do agente.
