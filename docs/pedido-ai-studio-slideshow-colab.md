# Pedido ao AI Studio: slideshow com trilha (grátis), escolha de motor (API / Colab) e vídeos curtos

Origem: o marketTon já gera imagens pelo AI Studio e monta slideshows por conta própria (ffmpeg, **sem música**). O operador quer
aproveitar o que o AI Studio tem: montagem gratuita com trilha, vídeos curtos de 5 a 10 s e as opções de GPU (Colab gratuito, Colab Pro e APIs).
O agente do marketTon usa tudo isso **sozinho**, então o contrato precisa dizer o estado de cada coisa (pronto, esperando GPU, sem saldo).

## 1. Slideshow com trilha (prioridade, custo quase zero)
- Novo `deliverable.kind = "slideshow"` (também em campanhas `image_only`): junta as imagens da própria campanha (4:5, 1:1, 9:16) **e as fotos do
  produto** em um vídeo vertical 9:16 de **10 a 15 s**, com zoom lento e transição suave (como `reels.py` do marketTon faz), **com trilha**.
- Trilha: pela API (`< US$ 0,01` segundo o contrato) ou biblioteca própria livre de direitos; sem voz; volume −14 LUFS. O contrato deve dizer a
  **licença de uso comercial** da trilha (decisão em aberto 8.c do contrato).
- Conferências como nas outras peças (duração, volume, nada cortado). Custo no `estimate` (esperado: centavos).

## 2. Escolha do motor
Hoje o contrato esconde o motor de propósito. Para o operador poder escolher e o agente respeitar o gasto, pedimos, **sem quebrar a v1**:
- Campo opcional `creative.compute`: `"auto"` (padrão: o servidor escolhe), `"api"` (só provedores pagos), `"colab_free"`, `"colab_pro"`.
- `GET /capabilities` passa a trazer `compute`: `{ "api": {"available": true}, "colab_free": {"available": false, "worker_online": false, "queue": 0},
  "colab_pro": {...} }`.
- Status novo de campanha/peça: `waiting_worker` (aguardando uma GPU do Colab ligar). Evento `campaign.waiting_worker` e, quando o worker entra,
  `campaign.progress`. **Sem worker online por mais de X horas** (padrão 24 h): `failed` com `worker_unavailable` ou, se `compute="auto"`, cai para API.
- `estimate` mostra `usd` por motor (Colab = 0 de crédito, mas com `eta_s` e o aviso "depende de o worker estar ligado").

## 3. Vídeos curtos de apresentação (5 a 10 s) e prova do produto por pessoa
- `limits.video_duration_s` hoje começa em 6 s: aceitar **5 s** para clipes curtos de produto (sem narração).
- Peça nova, só quando houver worker (Colab/GPU): `kind = "video"` com `presenter.type = "character"` (alguém usando/experimentando o produto),
  5 a 10 s, sem voz. Em `compute="api"` a campanha volta `validation_error` explicando que essa peça pede worker.
- Regras de conteúdo (as mesmas que o marketTon exige): produto idêntico à foto (conferência de visão), **aviso "gerado por IA"** na peça, sem
  promessa de caimento ou resultado, **recusar categorias íntimas** (lingerie/calcinha) e qualquer coisa que as plataformas restrinjam. O marketTon
  também revisa antes de publicar.

## 4. O que o marketTon fará quando isso existir
- Pedir `slideshow` no lugar do slideshow local mudo; o agente confere os quadros e publica o Reel **com música**.
- Mostrar o estado do motor e a fila na página Criativos; enquanto `waiting_worker`, o agente segue com o que estiver pronto.
- Usar `compute="colab_free"` só para o que o operador liberar, com teto de espera.

## Notas importantes (Colab)
- O Colab gratuito/Pro **não roda sozinho o dia todo**: precisa de uma sessão aberta no navegador do operador, tem limite de horas e de GPU
  (T4), e a Google restringe uso automatizado em produção. Trate como **modo sob demanda** (o operador liga o worker algumas horas por dia),
  nunca como o único caminho: `auto` deve cair para API quando não houver worker.
- O worker precisa de um canal seguro com o servidor (hoje há `AISTUDIO_WORKER_KEY`). O contrato não deve expor o endereço nem a chave.
