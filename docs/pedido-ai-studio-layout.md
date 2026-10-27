# Pedido ao AI Studio: ajustes na montagem das imagens (anúncios do Mural na Web)

Origem: revisão dos criativos reais gerados em 27/10/2026 (campanhas `cmp_82AC272C906C`, `cmp_E8823EB4D146`, `cmp_27845C7380C3`,
`cmp_4C240B3E0888`), imagens estáticas 4:5, 1:1 e 9:16, modo `images`. Tudo abaixo é **montagem de marca** (sem tocar no desenho da IA).

## 1. Logo como carimbo, sem cobrir nada

Hoje a logo fica no canto superior direito e **cobre o fim do título** (ex.: "Mini Lanterna Tática:", "Tenis Casual Adulto:", "Conforto e estilo para").

Pedido:
- A logo é um **carimbo de marca d'água**: pequena (cerca de 10–12% da largura), em um dos **cantos do rodapé** (inferior direito ou esquerdo),
  fora da área do título, do produto, do preço e do botão. Alternativa aceitável: canto superior direito **somente se** o título
  respeitar uma margem direita maior que a logo (largura da logo + 24 px).
- Regra de teste: a caixa da logo **nunca** pode intersectar a caixa do título, do preço, do botão ou do endereço. Se intersectar, mover
  para o outro canto do rodapé.
- Opcional no contrato: `brand.logo.placement` = `bottom_right` (padrão) | `bottom_left` | `top_right`.

## 2. Preço "de / por" legível (hoje some)

Hoje o "De R$ 65,99 por R$ 28,90" sai em **letra preta sobre cinza-escuro**, ilegível, e ainda **desenhado duas vezes** (uma linha escura
sobre a outra, "De R$ 65,99 por R$ 28,90" e "de R$ 65,99 por").

Pedido:
- Desenhar **uma única** linha de preço antigo, com o valor antigo **riscado**.
- Fundo **amarelo** (`#FFD400`) com texto **escuro** (`#171923`), contraste mínimo 4,5:1, cantos arredondados e margem interna.
  O preço atual continua no bloco vermelho da marca, com texto branco.
- Opcional no contrato: `brand.price_badge` = `{ "background": "#FFD400", "text": "#171923" }` e `brand.colors.highlight`.

## 3. Título sem encostar no produto

- Máximo de 2 linhas e cerca de 32 caracteres por linha; título mais longo quebra ou é abreviado antes de passar da largura útil.
- O bloco do título não pode cobrir o produto (ver legging: o bloco "você!" encosta na cintura do produto).

## Como validar

Regerar uma imagem de cada formato (4:5, 1:1, 9:16) para os produtos de teste (garrafa, lanterna, legging) e conferir: logo sem
sobreposição, preço antigo único e legível, título dentro da área útil. O marketTon pede só `formats: "images"`.
