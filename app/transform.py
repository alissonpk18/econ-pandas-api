"""Núcleo de transformação com Pandas.

Cada função é pura e testável sem rede: recebe estruturas Python/pandas e
devolve Series/DataFrame/dict. O acesso à rede fica isolado em ``bcb_client``.
É aqui que mora a competência analítica do projeto — parsing de dados "sujos",
mensalização, variações MoM/YoY, média móvel, merge de séries, juro real e
qualidade de dados.
"""
from __future__ import annotations

import pandas as pd


# --------------------------------------------------------------------------- #
# Parsing / limpeza
# --------------------------------------------------------------------------- #
def parse_sgs(registros: list[dict]) -> pd.Series:
    """Converte o JSON cru do SGS numa Series numérica indexada por data.

    O SGS devolve datas como texto ``dd/mm/aaaa`` e valores como string
    (``"4.50"``). Normalizamos para um ``DatetimeIndex`` ordenado e valores
    ``float``. Linhas com data ou valor inválidos são descartadas.
    """
    if not registros:
        return pd.Series(
            dtype="float64",
            name="valor",
            index=pd.DatetimeIndex([], name="data"),
        )

    df = pd.DataFrame(registros)
    datas = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="coerce")
    valores = pd.to_numeric(df["valor"], errors="coerce")

    s = pd.Series(
        valores.to_numpy(),
        index=pd.DatetimeIndex(datas, name="data"),
        name="valor",
    )
    s = s[s.index.notna()]  # descarta datas que não parsearam (NaT)
    s = s.dropna()          # descarta valores que não parsearam (NaN)
    return s.sort_index()


# --------------------------------------------------------------------------- #
# Reamostragem e variações
# --------------------------------------------------------------------------- #
def to_monthly(s: pd.Series) -> pd.Series:
    """Mensaliza a série pegando o último valor de cada mês (``"ME"``)."""
    return s.resample("ME").last()


def mom_change(s: pd.Series) -> pd.Series:
    """Variação mês a mês (period-over-period) como fração: ``0.012`` = 1,2%."""
    return s.pct_change()


def yoy_change(s: pd.Series, periodos: int = 12) -> pd.Series:
    """Variação ano a ano (``periodos`` à frente) como fração."""
    return s.pct_change(periodos)


def rolling_mean(s: pd.Series, janela: int = 12) -> pd.Series:
    """Média móvel de ``janela`` períodos."""
    return s.rolling(janela).mean()


def accumulated_inflation(ipca_pct: pd.Series) -> pd.Series:
    """Índice de inflação acumulada a partir da variação % mensal.

    Aplica ``(1 + ipca/100).cumprod()``. O resultado começa próximo de 1.0;
    subtraia 1 e multiplique por 100 para ler como inflação acumulada em %.
    """
    return (1 + ipca_pct / 100).cumprod()


# --------------------------------------------------------------------------- #
# Merge / alinhamento
# --------------------------------------------------------------------------- #
def merge_series(
    esquerda: pd.Series,
    direita: pd.Series,
    nome_esq: str,
    nome_dir: str,
    como: str = "outer",
) -> pd.DataFrame:
    """Alinha duas séries por data num DataFrame (join pelo índice).

    O padrão ``"outer"`` expõe o desalinhamento: datas presentes em só uma das
    séries viram ``NaN`` na outra coluna.
    """
    df = pd.merge(
        esquerda.rename(nome_esq).to_frame(),
        direita.rename(nome_dir).to_frame(),
        left_index=True,
        right_index=True,
        how=como,
    )
    return df.sort_index()


# --------------------------------------------------------------------------- #
# Qualidade de dados (o diferencial "sênior")
# --------------------------------------------------------------------------- #
def detect_gaps(s: pd.Series, max_dias: int = 35) -> list[dict]:
    """Detecta lacunas temporais via diferença entre datas consecutivas.

    Usa ``index.to_series().diff()``: qualquer intervalo maior que ``max_dias``
    é reportado como lacuna. O padrão de 35 dias cobre séries mensais; para
    séries diárias, use algo como 5 (3 dias já cobre fins de semana).
    """
    if len(s) < 2:
        return []

    deltas = s.index.to_series().diff()
    lacunas: list[dict] = []
    for fim, delta in deltas.items():
        if pd.notna(delta) and delta.days > max_dias:
            inicio = fim - delta
            lacunas.append(
                {
                    "de": inicio.date().isoformat(),
                    "ate": fim.date().isoformat(),
                    "dias": int(delta.days),
                }
            )
    return lacunas


def quality_report(s: pd.Series, freq: str = "M", max_dias_lacuna: int = 35) -> dict:
    """Relatório de qualidade de uma série.

    - ``total_pontos`` e período coberto;
    - ``pct_faltante``: % de períodos ausentes vs. a grade esperada;
    - ``ultima_atualizacao`` e ``defasagem_dias`` (freshness);
    - ``lacunas``: buracos detectados pela diferença entre datas.

    ``freq`` controla a grade esperada para o % de faltantes:
    ``"M"`` (mensal), ``"B"`` (dias úteis) ou ``"D"`` (dias corridos).
    """
    if s.empty:
        return {
            "total_pontos": 0,
            "inicio": None,
            "fim": None,
            "pct_faltante": None,
            "ultima_atualizacao": None,
            "defasagem_dias": None,
            "lacunas": [],
        }

    inicio, fim = s.index.min(), s.index.max()

    if freq == "M":
        presentes = s.index.to_period("M").nunique()
        esperado = len(pd.period_range(inicio, fim, freq="M"))
    elif freq == "B":
        presentes = s.index.normalize().nunique()
        esperado = len(pd.bdate_range(inicio, fim))
    else:  # "D" — dias corridos
        presentes = s.index.normalize().nunique()
        esperado = len(pd.date_range(inicio, fim, freq="D"))

    pct_faltante = (
        round(100 * (esperado - presentes) / esperado, 2) if esperado else 0.0
    )
    defasagem = int((pd.Timestamp.today().normalize() - fim.normalize()).days)

    return {
        "total_pontos": int(len(s)),
        "inicio": inicio.date().isoformat(),
        "fim": fim.date().isoformat(),
        "pct_faltante": float(pct_faltante),
        "ultima_atualizacao": fim.date().isoformat(),
        "defasagem_dias": defasagem,
        "lacunas": detect_gaps(s, max_dias=max_dias_lacuna),
    }


# --------------------------------------------------------------------------- #
# Indicadores derivados
# --------------------------------------------------------------------------- #
def summary(s: pd.Series, janela: int = 12) -> dict:
    """Resumo de uma série: último valor, MoM, YoY, média móvel, mín/máx.

    A série é mensalizada antes do cálculo, então funciona tanto para séries
    diárias (Selic, dólar) quanto para mensais (IPCA). As variações são frações.
    """
    if s.empty:
        return {
            "ultimo_valor": None,
            "data_ultimo": None,
            "variacao_mom": None,
            "variacao_yoy": None,
            "media_movel_12m": None,
            "minimo": None,
            "maximo": None,
        }

    mensal = to_monthly(s)
    mom = mom_change(mensal)
    yoy = yoy_change(mensal)
    media = rolling_mean(mensal, janela)

    def _f(x: object) -> float | None:
        return float(x) if pd.notna(x) else None

    return {
        "ultimo_valor": _f(mensal.iloc[-1]),
        "data_ultimo": mensal.index[-1].date().isoformat(),
        "variacao_mom": _f(mom.iloc[-1]),
        "variacao_yoy": _f(yoy.iloc[-1]),
        "media_movel_12m": _f(media.iloc[-1]),
        "minimo": _f(mensal.min()),
        "maximo": _f(mensal.max()),
    }


def real_interest(selic_anual: pd.Series, ipca_mensal: pd.Series) -> pd.DataFrame:
    """Juro real ex-post pela equação de Fisher.

    Parâmetros
    ----------
    selic_anual:
        Taxa nominal anualizada em % a.a. (ex.: Selic meta, cód. 432).
    ipca_mensal:
        Variação mensal do IPCA em % a.m. (cód. 433).

    A inflação é acumulada em 12 meses a partir da variação mensal e então:

        juro_real = ((1 + selic/100) / (1 + ipca_12m/100) - 1) * 100

    Retorna um DataFrame mensal com as colunas ``selic``, ``ipca_12m`` e
    ``juro_real`` (todas em %), apenas para os meses com sobreposição válida.
    """
    selic_m = to_monthly(selic_anual)

    # Inflação acumulada em 12 meses (produto dos fatores mensais).
    fator_12m = (1 + ipca_mensal / 100).rolling(12).apply(
        lambda janela: janela.prod(), raw=True
    )
    ipca_12m = (fator_12m - 1) * 100

    # Normaliza ambos os índices para o início do mês, alinhando o IPCA
    # (datado no 1º dia do mês de referência) com a Selic (fim de mês).
    selic_m.index = selic_m.index.to_period("M").to_timestamp()
    ipca_12m.index = ipca_12m.index.to_period("M").to_timestamp()

    df = merge_series(selic_m, ipca_12m, "selic", "ipca_12m", como="inner").dropna()
    df["juro_real"] = (
        (1 + df["selic"] / 100) / (1 + df["ipca_12m"] / 100) - 1
    ) * 100
    return df
