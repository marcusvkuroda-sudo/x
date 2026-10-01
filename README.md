# 💸 Nossos Gastos

App local para o casal controlar os gastos: lançamentos manuais, leitura automática de faturas
do cartão pelo Claude e um painel visual com tudo organizado.

Roda num computador de casa e vocês dois acessam pelo navegador do PC ou do celular, na mesma
Wi-Fi. Os dados ficam só nesse computador (arquivo `data/gastos.db`).

## O que tem

- **Painel**: total do período comparado ao período anterior, média por mês/dia, maior categoria,
  evolução mês a mês empilhada por categoria, ranking de categorias, calendário de calor dos dias,
  média por dia da semana, top estabelecimentos e parcelas que ainda vão vencer. Filtros por período,
  mês, categoria e cartão. Tem modo escuro.
- **Importar fatura**: envie o PDF da fatura (inclusive os protegidos por senha) ou fotos das páginas.
  O Claude extrai cada lançamento (data, estabelecimento, valor, categoria, parcela, estornos), ignora
  pagamentos da fatura anterior e confere a soma com o total impresso. Vocês revisam, ajustam o que
  quiserem e confirmam. Lançamentos que parecem já existir chegam desmarcados.
- **Lançamentos**: lista por mês com busca e filtros. Toque num lançamento para editar ou excluir.
  O botão **＋ Novo gasto** adiciona um gasto manual em segundos. Dá para exportar tudo em CSV.

## Como instalar

Requisitos: **Python 3.10 ou mais novo** ([python.org](https://www.python.org/downloads/)) e uma
**chave da API da Anthropic** ([console.anthropic.com](https://console.anthropic.com/settings/keys)).

1. Baixe esta pasta para o computador que vai ficar ligado em casa.
2. Dê dois cliques em **`iniciar.bat`** (Windows) ou rode `./iniciar.sh` no Terminal (macOS/Linux).
   Na primeira vez ele instala as dependências e cria o arquivo `.env`.
3. Abra o `.env`, cole a chave em `ANTHROPIC_API_KEY=` e rode o script de novo.
4. O terminal mostra dois endereços:
   - **Neste computador**: `http://localhost:8000`
   - **Nos celulares**: algo como `http://192.168.0.15:8000`. Abra no celular conectado à mesma Wi-Fi.

No celular, use "Adicionar à tela de início" (Safari ou Chrome) para abrir como se fosse um app.

> **Windows:** na primeira execução o Windows pode perguntar se o Python pode acessar a rede.
> Permita em **redes privadas**, senão os celulares não conseguem abrir o app.

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
| `APP_PASSWORD` | Opcional: o navegador pede essa senha ao abrir o app (qualquer usuário serve) |
| `EXTRACTION_MODEL` | Modelo usado na leitura (padrão `claude-opus-5-5`) |
| `EXTRACTION_EFFORT` | `low`, `medium` (padrão) ou `high`. Mais esforço deixa a leitura mais cuidadosa e mais cara |
| `PORT` | Porta do servidor (padrão 8000) |
| `DATA_DIR` | Pasta onde ficam o banco e as faturas enviadas (padrão `data/`) |

## Custos e privacidade

- Lançamentos manuais e o painel não usam a API e não custam nada.
- Cada fatura importada é enviada uma única vez para a API da Anthropic, só para ser lida. O custo
  real de cada leitura aparece no histórico de importações. Uma fatura típica de cartão costuma ficar
  na casa de alguns centavos de dólar.
- A senha do PDF serve só para abrir o arquivo e não é salva.
- O banco e as faturas enviadas ficam em `data/`. **Para fazer backup, copie essa pasta.**

## Quer ver o painel com dados de exemplo?

```bash
DATA_DIR=data-demo python scripts/demo_data.py
DATA_DIR=data-demo python run.py
```

Isso cria 12 meses de gastos fictícios numa pasta separada e não mexe nos dados de vocês.

## Para quem for mexer no código

- `app/main.py`: API (FastAPI) e servidor dos arquivos do front
- `app/extractor.py`: prompt e chamada ao Claude, com saída estruturada (JSON Schema)
- `app/documents.py`: preparo dos arquivos (decripta PDFs, converte HEIC/fotos para JPEG)
- `app/categories.py`: categorias fixas (a ordem define as cores do painel)
- `static/`: front-end em HTML/CSS/JS puro, gráficos em SVG feitos à mão, sem build

Testes: `pip install -r requirements-dev.txt && python -m pytest`
