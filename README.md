# 💸 Nossos Gastos

App local para o casal controlar os gastos: lançamentos manuais, leitura automática das faturas
do cartão (de graça) e um painel visual com tudo organizado.

Roda num computador de casa, e vocês dois acessam pelo navegador do PC ou do celular, na mesma
Wi-Fi. Os dados ficam só nesse computador, na pasta `data/`.

## O que tem

- **Painel**:
  - Total do período comparado ao período anterior.
  - Média por mês (sem contar o mês em andamento) ou por dia.
  - Evolução mês a mês empilhada por categoria e ranking de categorias com a variação de cada uma.
  - Calendário de calor dos dias, média por dia da semana e top estabelecimentos.
  - Parcelas que ainda vão vencer.
  - Filtros por período, mês, categoria e cartão, e modo escuro.
  - **Mês da fatura** (padrão) ou **data da compra**: no primeiro, cada lançamento importado conta no
    mês de vencimento da sua fatura, então o total do mês bate exatamente com a fatura do banco; no
    segundo, conta no mês em que a compra foi feita.
  - Quando o mês atual ainda não tem gastos (a fatura só chega depois), o painel abre no último mês que tem dados.
- **Importar fatura (gratuito)**: envie o PDF da fatura baixado do app ou site do banco (inclusive
  os protegidos por senha), ou o arquivo CSV/OFX que o banco exporta.
  - O app lê o texto do PDF e extrai cada lançamento (data, estabelecimento, valor, parcela, estornos),
    sem IA e sem internet. A categoria vem de uma lista de palavras-chave e da memória de categorias.
  - Ignora o pagamento da fatura anterior e as parcelas futuras.
  - Confere a soma com o total impresso na fatura.
  - Vocês revisam, ajustam o que quiserem e confirmam. Lançamentos que parecem já existir chegam desmarcados.
- **Memória de categorias**: corrigiu a categoria de um estabelecimento? O app lembra e aplica nas
  próximas faturas, com a etiqueta "categoria lembrada". Na revisão, a correção vale também para os
  lançamentos iguais da mesma fatura. Ao editar um lançamento antigo, dá para aplicar a nova categoria
  a todos os outros do mesmo lugar de uma vez.
- **Lançamentos**:
  - Lista por mês com total, busca sem acento (e por valor, como "45,90") e filtros.
  - Toque num lançamento para editar, excluir ou **duplicar**, o que é útil para aluguel, contas fixas e a próxima parcela.
  - O botão **＋ Novo gasto** adiciona um gasto manual em segundos.
  - Dá para exportar tudo em CSV.

## Como instalar

Requisito: **Python 3.10 ou mais novo** ([python.org](https://www.python.org/downloads/)). Nada mais
é obrigatório: a leitura de faturas é gratuita.

> No Mac, o `python3` que já vem no sistema é o 3.9, antigo demais: instale o do python.org.
> No Windows, marque **"Add python.exe to PATH"** durante a instalação.

1. Baixe esta pasta para o computador que vai ficar ligado em casa.
2. Inicie o app:
   - **Windows**: dê dois cliques em `iniciar.bat`.
   - **Mac/Linux**: abra o Terminal na pasta e rode `bash iniciar.sh`.

   Na primeira vez ele instala as dependências e cria o arquivo `.env`.
3. (Recomendado) Abra o `.env`, defina uma senha em `APP_PASSWORD=` e inicie de novo.
4. O terminal mostra dois endereços:
   - **Neste computador**: `http://localhost:8000`
   - **Nos celulares**: algo como `http://192.168.0.15:8000`. Abra no celular conectado à mesma Wi-Fi.

No celular, use "Adicionar à tela de início" (Safari ou Chrome) para abrir como se fosse um app.

Dicas:
- O computador precisa estar ligado e acordado para os celulares acessarem; ajuste o modo de
  suspensão se for o caso.
- Se o endereço dos celulares parar de funcionar, o roteador pode ter trocado o IP do computador:
  inicie o app de novo e veja o endereço atualizado.
- **Windows:** na primeira execução o Windows pode perguntar se o Python pode acessar a rede.
  Permita em **redes privadas**, senão os celulares não conseguem abrir o app.

Instalação manual, se preferir:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # e preencha a chave
python run.py
```

## Configurações (`.env`)

| Variável | Para que serve |
|---|---|
| `ANTHROPIC_API_KEY` | Opcional e pago à parte: com ela, PDFs e fotos são lidos pelo Claude (veja abaixo) |
| `EXTRACTION_MODE` | `auto` (padrão: Claude se houver chave, senão gratuito), `local` (sempre gratuito) ou `claude` |
| `APP_PASSWORD` | Opcional, mas recomendado: o navegador pede essa senha ao abrir o app (qualquer usuário serve). Sem ela, qualquer pessoa na sua Wi-Fi consegue abrir os gastos |
| `EXTRACTION_MODEL` | Modelo usado na leitura (padrão `claude-opus-5-5`; `claude-sonnet-5-5` custa cerca de metade) |
| `EXTRACTION_EFFORT` | `low`, `medium` (padrão) ou `high`. Mais esforço deixa a leitura mais cuidadosa e mais cara |
| `PORT` | Porta do servidor (padrão 8000) |
| `DATA_DIR` | Pasta onde ficam o banco, os backups e as faturas enviadas (padrão `data/`) |

## Leitura gratuita, opções e limites

- **PDF do banco**: funciona com faturas geradas pelo banco (que têm texto dentro). PDFs escaneados ou
  fotos não têm texto: para esses, exporte CSV/OFX ou use a dica do Claude abaixo.
- **CSV/OFX**: o jeito mais preciso. O Nubank, por exemplo, exporta a fatura em CSV no app e no site.
- **Senha do PDF**: normalmente são os primeiros dígitos do CPF do titular. O app perdoa espaços e
  pontos digitados a mais, e abre sem senha os PDFs que só bloqueiam impressão.
- **Faturas em duas colunas** e com colunas de parcela e de US$ (como a do Santander) são lidas coluna
  por coluna, sempre pelo valor em R$.
- **Algum banco não funcionou?** Cada banco monta o PDF de um jeito; o leitor é genérico. Avise qual
  banco e ajustamos o código.
- **Fotos, sem pagar nada**: envie a foto ou PDF numa conversa no claude.ai (assinatura Pro) pedindo
  "transforme os lançamentos desta fatura em CSV com as colunas data;descricao;valor" e importe o CSV.
- **Leitura pelo Claude (paga)**: com `ANTHROPIC_API_KEY` no `.env`, PDFs e fotos são lidos pela API da
  Anthropic, cobrada à parte da assinatura do Claude (algo como US$ 0,10 a 0,40 por fatura). CSV/OFX
  continuam sendo lidos de graça.

## Bancos conectados (Open Finance, grátis)

Em vez de baixar faturas, o app pode buscar os gastos direto do banco pelo **Meu Pluggy**, que é
gratuito para as suas próprias contas (até 5 conexões, todas do mesmo titular).

1. Em [meu.pluggy.ai](https://meu.pluggy.ai), conecte o Inter e o Santander (autorização pelo app de cada banco).
2. Em [dashboard.pluggy.ai](https://dashboard.pluggy.ai), crie uma aplicação e copie o **Client ID**, o
   **Client Secret** e o **Item ID** de cada banco conectado.
3. No app, aba **Importar → 🏦 Bancos conectados → Conectar bancos**, cole os três e clique em
   **Testar e salvar**. O app confere na hora se está tudo certo e mostra o nome de cada banco.
4. Clique em **🔄 Sincronizar agora**. Os gastos chegam na mesma tela de revisão das faturas: confira,
   ajuste categorias e importe.

- A primeira sincronização traz os últimos 90 dias; as próximas só o que for novo (nada entra duas vezes).
- Entram só **compras no cartão de crédito** (o que vai para a fatura) e **compras no cartão de débito**
  (estacionamento, um café). Pix enviados ou recebidos, boletos, transferências, TED, salário e
  aplicações ficam de fora: aluguel e contas vão em **Gastos fixos** (abaixo).
- Compras no cartão contam no mês da fatura em que caem, inclusive as da fatura ainda aberta.
- A categoria vem, nesta ordem: das correções que vocês já fizeram, do tipo do estabelecimento
  informado pela bandeira do cartão (MCC), da categoria da Pluggy e, por último, das palavras da
  descrição. Corrigiu uma? O app lembra nas próximas.
- Se um banco aparecer como "reconecte no meu.pluggy.ai", renove a autorização lá (o Open Finance pede
  isso de tempos em tempos).
- As chaves ficam só no computador, em `data/pluggy.json` (o app nunca mostra o Client Secret de volta).
  Quem preferir pode usar `PLUGGY_CLIENT_ID`, `PLUGGY_CLIENT_SECRET` e `PLUGGY_ITEM_IDS` no `.env`.
- Se você já importou o PDF de uma fatura, a sincronização marca os lançamentos iguais como
  "possível duplicado" e os deixa desmarcados.

## Gastos fixos

Na aba **🔁 Fixos**, cadastre uma vez o que se repete todo mês (aluguel, condomínio, internet, escola,
plano de saúde): valor, categoria, dia e a partir de que mês. O app lança o gasto sozinho em cada mês,
desde o mês inicial até o mês atual, e no começo de cada mês novo.

- Mudou o valor (reajuste do aluguel)? Edite: vale deste mês em diante, ou marque para corrigir
  também os meses anteriores.
- Uma conta veio diferente num mês (luz mais cara)? Edite só aquele lançamento em **Lançamentos**.
- Acabou? Preencha "Até" ou exclua; os meses já lançados ficam, a menos que você peça para apagar.

## Privacidade e backup

- Na leitura gratuita nada sai do computador.
- A senha do PDF serve só para abrir o arquivo e não é salva.
- O app guarda sozinho uma cópia diária do banco em `data/backups/` (as últimas 14), sempre ao
  iniciar e antes de excluir uma importação. Para desfazer um estrago, pare o app e copie o backup
  do dia desejado por cima de `data/gastos.db`.
- Essas cópias ficam no mesmo computador. **Para se proteger de perder o computador, copie de vez
  em quando a pasta `data/`** para um pendrive ou para a nuvem.

## Quer ver o painel com dados de exemplo?

```bash
DATA_DIR=data-demo python scripts/demo_data.py
DATA_DIR=data-demo python run.py
```

Isso cria 12 meses de gastos fictícios numa pasta separada e não mexe nos dados de vocês.

## Para quem for mexer no código

- `app/main.py`: API (FastAPI) e servidor dos arquivos do front
- `app/local_reader.py`: leitura gratuita de PDF (texto), CSV e OFX
- `app/categorizer.py`: categorias por palavras-chave e limpeza do nome do estabelecimento
- `app/extractor.py`: prompt e chamada ao Claude, com saída estruturada (JSON Schema) e limpeza do resultado (opcional, pago)
- `app/documents.py`: preparo dos arquivos (decripta PDFs, converte HEIC/fotos para JPEG no tamanho que o modelo enxerga)
- `app/rules.py`: memória de categorias
- `app/categories.py`: categorias fixas (a ordem define as cores do painel)
- `static/`: front-end em HTML/CSS/JS puro, gráficos em SVG feitos à mão, sem build

Testes: `pip install -r requirements-dev.txt && python -m pytest`
