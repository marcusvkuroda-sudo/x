# 💸 Nossos Gastos

App local para o casal controlar os gastos: lançamentos manuais, leitura automática de faturas
do cartão pelo Claude e um painel visual com tudo organizado.

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
  - Quando o mês atual ainda não tem gastos (a fatura só chega depois), o painel abre no último mês que tem dados.
- **Importar fatura**: envie o PDF da fatura, inclusive os protegidos por senha, ou fotos das páginas.
  - O Claude extrai cada lançamento (data, estabelecimento, valor, categoria, parcela, estornos).
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

Requisitos: **Python 3.10 ou mais novo** ([python.org](https://www.python.org/downloads/)) e uma
**chave da API da Anthropic** ([console.anthropic.com](https://console.anthropic.com/settings/keys)).

> No Mac, o `python3` que já vem no sistema é o 3.9, antigo demais: instale o do python.org.
> No Windows, marque **"Add python.exe to PATH"** durante a instalação.

1. Baixe esta pasta para o computador que vai ficar ligado em casa.
2. Inicie o app:
   - **Windows**: dê dois cliques em `iniciar.bat`.
   - **Mac/Linux**: abra o Terminal na pasta e rode `bash iniciar.sh`.

   Na primeira vez ele instala as dependências e cria o arquivo `.env`.
3. Abra o `.env`, cole a chave em `ANTHROPIC_API_KEY=` e inicie de novo.
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
| `ANTHROPIC_API_KEY` | Chave da API usada para ler as faturas (obrigatória só para importar) |
| `APP_PASSWORD` | Opcional, mas recomendado: o navegador pede essa senha ao abrir o app (qualquer usuário serve). Sem ela, qualquer pessoa na sua Wi-Fi consegue abrir os gastos |
| `EXTRACTION_MODEL` | Modelo usado na leitura (padrão `claude-opus-5-5`; `claude-sonnet-5-5` custa cerca de metade) |
| `EXTRACTION_EFFORT` | `low`, `medium` (padrão) ou `high`. Mais esforço deixa a leitura mais cuidadosa e mais cara |
| `PORT` | Porta do servidor (padrão 8000) |
| `DATA_DIR` | Pasta onde ficam o banco, os backups e as faturas enviadas (padrão `data/`) |

## Custos, privacidade e backup

- Lançamentos manuais e o painel não usam a API e não custam nada.
- Cada fatura importada é enviada uma única vez para a API da Anthropic, só para ser lida. Pela
  tabela de preços, uma fatura de 5 a 10 páginas deve custar algo entre US$ 0,10 e US$ 0,40. O custo
  real de cada leitura aparece no histórico de importações.
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
- `app/extractor.py`: prompt e chamada ao Claude, com saída estruturada (JSON Schema) e limpeza do resultado
- `app/documents.py`: preparo dos arquivos (decripta PDFs, converte HEIC/fotos para JPEG no tamanho que o modelo enxerga)
- `app/rules.py`: memória de categorias
- `app/categories.py`: categorias fixas (a ordem define as cores do painel)
- `static/`: front-end em HTML/CSS/JS puro, gráficos em SVG feitos à mão, sem build

Testes: `pip install -r requirements-dev.txt && python -m pytest`
