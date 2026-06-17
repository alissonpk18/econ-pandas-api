# API de Indicadores Econômicos BR 🇧🇷

API que puxa séries temporais do **Banco Central (SGS)**, trata os dados com
**Pandas** e expõe indicadores prontos via **FastAPI** — com uma camada extra de
**qualidade de dados** (freshness, lacunas, % de faltantes).

A fonte foi escolhida de propósito: o SGS devolve dados "sujos" (datas como texto
`dd/mm/aaaa`, valores como string) e temporais, o que obriga a fazer Pandas de
verdade — parsing, resample, variação YoY, média móvel, merge de séries.

> ⚙️ Stack: FastAPI · Pandas · httpx · Pydantic v2 · pytest · Docker

---

## Fonte de dados (sem autenticação)

```
https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json&dataInicial=01/01/2020
→ [{"data":"01/01/2020","valor":"4.50"}, ...]
```

Séries no catálogo (`app/config.py`):

| Código | Indicador  | Unidade | Frequência |
| -----: | ---------- | ------- | ---------- |
|    433 | IPCA       | % a.m.  | mensal     |
|     11 | Selic      | % a.d.  | diária     |
|    432 | Selic Meta | % a.a.  | diária     |
|     12 | CDI        | % a.d.  | diária     |
|      1 | Dólar PTAX | R$/US$  | diária     |

---

## Endpoints

| Método | Rota                                   | O que faz                                                            |
| ------ | -------------------------------------- | ------------------------------------------------------------------- |
| `GET`  | `/health`                              | Liveness                                                            |
| `GET`  | `/series/{codigo}?inicio=&fim=`        | Série tratada de um indicador                                       |
| `GET`  | `/indicadores/{codigo}/resumo`         | Último valor, MoM, YoY, média móvel 12m, mín/máx                    |
| `GET`  | `/indicadores/comparar?codigos=11,433` | Duas (ou mais) séries alinhadas por data (merge)                    |
| `GET`  | `/indicadores/juro-real`               | Juro real (Selic meta vs. IPCA 12m) pela equação de Fisher          |
| `GET`  | `/indicadores/{codigo}/qualidade`      | Relatório de qualidade: % faltante, freshness, lacunas detectadas   |

> As datas em `inicio`/`fim` seguem o formato do SGS: `dd/mm/aaaa`.

Documentação interativa (Swagger) gerada automaticamente em **`/docs`**.

---

## O Pandas que importa

Cada técnica vira uma função pequena e testável em [`app/transform.py`](app/transform.py):

| Técnica                                    | Função                  |
| ------------------------------------------ | ----------------------- |
| `to_datetime(..., format="%d/%m/%Y")` + `to_numeric` | `parse_sgs`   |
| `resample("ME").last()` (mensalização)     | `to_monthly`            |
| `pct_change()` / `pct_change(12)` (MoM/YoY) | `mom_change` / `yoy_change` |
| `rolling(12).mean()` (média móvel)         | `rolling_mean`          |
| `(1 + ipca/100).cumprod()` (inflação acum.) | `accumulated_inflation` |
| `merge`/`join` por data (desalinhamento)   | `merge_series`          |
| `index.to_series().diff()` (lacunas)        | `detect_gaps`           |
| % faltante + freshness                     | `quality_report`        |
| Equação de Fisher (juro real)              | `real_interest`         |

---

## Como rodar

Requer **Python 3.11+**.

```powershell
# 1. Ambiente virtual (PowerShell, Windows)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Dependências
pip install -r requirements.txt

# 3. Sobe a API
uvicorn app.main:app --reload
```

```bash
# Equivalente em bash/Linux/macOS
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abra **http://127.0.0.1:8000/docs**.

### Exemplos

```bash
curl "http://127.0.0.1:8000/indicadores/433/resumo"
curl "http://127.0.0.1:8000/indicadores/comparar?codigos=11,433"
curl "http://127.0.0.1:8000/indicadores/juro-real"
curl "http://127.0.0.1:8000/indicadores/433/qualidade"
```

Resposta de `/indicadores/juro-real` (exemplo abreviado):

```json
{
  "metodo": "Fisher: ((1+Selic)/(1+IPCA_12m) - 1) * 100",
  "fonte_selic": "SGS 432 (Selic Meta)",
  "fonte_ipca": "SGS 433 (IPCA)",
  "n": 60,
  "ultimo": { "data": "2024-12-01", "selic": 12.25, "ipca_12m": 4.83, "juro_real": 7.08 }
}
```

---

## Testes

A suíte cobre o núcleo Pandas **sem rede** (o cliente SGS é testado via
`monkeypatch`), então roda offline e rápido:

```bash
pytest -q
```

---

## Docker

```bash
docker build -t indicadores-economicos-api .
docker run -p 8000:8000 indicadores-economicos-api
```

---

## Decisões de modelagem

- **Selic: meta vs. efetiva.** Para juro real usamos a **meta Selic (cód. 432)**,
  que já é anualizada (% a.a.) e é a taxa que o mercado cita. A efetiva diária
  (cód. 11, % a.d.) também está no catálogo, exposta como série.
- **Juro real ex-post (Fisher).** A inflação é acumulada em 12 meses a partir da
  variação mensal do IPCA e combinada com a Selic por
  `((1 + selic/100) / (1 + ipca_12m/100) - 1) * 100`, em vez da subtração
  simples — o resultado é o juro real correto, não uma aproximação.
- **Alinhamento de datas.** O IPCA é datado no 1º dia do mês de referência e as
  séries diárias no fim do mês; normalizamos ambos para o início do mês (via
  `Period`) antes de qualquer merge.
- **Qualidade de dados.** O % de faltantes compara a série a uma grade esperada
  (mensal ou de dias úteis); a freshness mede a defasagem desde a última
  observação; e as lacunas saem da diferença entre datas consecutivas.

> Os códigos do SGS podem ter variações — confirme sempre no
> [catálogo oficial](https://www3.bcb.gov.br/sgspub/localizarseries/localizarSeries.do).

---

## Estrutura

```
.
├── app/
│   ├── main.py          # FastAPI + rotas
│   ├── bcb_client.py    # fetch do SGS (httpx) + cache em memória
│   ├── transform.py     # núcleo Pandas (puro, testável)
│   ├── models.py        # schemas Pydantic de resposta
│   └── config.py        # catálogo de séries e constantes
├── tests/
│   └── test_transform.py
├── requirements.txt
├── pyproject.toml
├── Dockerfile
└── README.md
```

## Próximos passos

- Persistir séries (SQLite/Parquet) para histórico e respostas offline.
- Cache HTTP com `Cache-Control`/ETag além do cache em memória.
- Mais indicadores (IGP-M, desemprego PNAD, expectativas Focus).
- CI (GitHub Actions) rodando `pytest` a cada push.
