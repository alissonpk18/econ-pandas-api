"""FastAPI + rotas da API de Indicadores Econômicos BR.

Seis rotas coerentes. Cada uma busca o dado cru no SGS (``bcb_client``),
limpa e transforma com Pandas (``transform``) e devolve um schema Pydantic.
"""
from __future__ import annotations

import pandas as pd
from fastapi import FastAPI, HTTPException, Query

from . import transform
from .bcb_client import BCBError, fetch_serie
from .config import COD_IPCA, COD_SELIC_META, JANELA_MOVEL, SERIES, Serie
from .models import (
    ComparacaoResponse,
    HealthResponse,
    JuroRealResponse,
    Lacuna,
    Ponto,
    PontoComparacao,
    PontoJuroReal,
    QualidadeResponse,
    ResumoResponse,
    SerieResponse,
)

app = FastAPI(
    title="API de Indicadores Econômicos BR",
    description=(
        "Séries temporais do Banco Central (SGS) tratadas com Pandas e expostas "
        "como indicadores prontos: resumo estatístico, comparação de séries, "
        "juro real (Selic vs. IPCA) e relatórios de qualidade de dados."
    ),
    version="1.0.0",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _serie_meta(codigo: int) -> Serie:
    """Devolve os metadados da série ou levanta 404 se o código não está no catálogo."""
    meta = SERIES.get(codigo)
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"Série {codigo} fora do catálogo. Conhecidas: {sorted(SERIES)}.",
        )
    return meta


def _carregar(
    codigo: int, inicio: str | None = None, fim: str | None = None
) -> pd.Series:
    """Busca + limpa uma série, ou levanta HTTPException apropriada."""
    try:
        cru = fetch_serie(codigo, inicio, fim)
    except BCBError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    s = transform.parse_sgs(cru)
    if s.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Sem dados para a série {codigo} no período informado.",
        )
    return s


# --------------------------------------------------------------------------- #
# Rotas
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
def raiz():
    return {"servico": app.title, "docs": "/docs", "health": "/health"}


@app.get("/health", response_model=HealthResponse, tags=["infra"])
def health():
    """Liveness."""
    return HealthResponse()


@app.get("/series/{codigo}", response_model=SerieResponse, tags=["séries"])
def serie(
    codigo: int,
    inicio: str | None = Query(None, examples=["01/01/2020"]),
    fim: str | None = Query(None, examples=["31/12/2024"]),
):
    """Série tratada de um indicador (datas ISO, valores float)."""
    meta = _serie_meta(codigo)
    s = _carregar(codigo, inicio, fim)
    pontos = [
        Ponto(data=idx.date().isoformat(), valor=float(v)) for idx, v in s.items()
    ]
    return SerieResponse(
        codigo=codigo,
        nome=meta.nome,
        unidade=meta.unidade,
        inicio=pontos[0].data,
        fim=pontos[-1].data,
        n=len(pontos),
        pontos=pontos,
    )


# IMPORTANTE: rotas de segmento fixo (comparar, juro-real) declaradas antes das
# rotas com {codigo} para evitar ambiguidade de roteamento.
@app.get("/indicadores/comparar", response_model=ComparacaoResponse, tags=["indicadores"])
def comparar(
    codigos: str = Query(..., examples=["11,433"], description="códigos separados por vírgula"),
    inicio: str | None = Query(None, examples=["01/01/2020"]),
    fim: str | None = None,
):
    """Duas (ou mais) séries mensalizadas e alinhadas por data (merge)."""
    try:
        lista = [int(c.strip()) for c in codigos.split(",") if c.strip()]
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="codigos deve ser uma lista separada por vírgula, ex.: 11,433",
        ) from exc
    if len(lista) < 2:
        raise HTTPException(
            status_code=400, detail="Informe ao menos dois códigos, ex.: codigos=11,433"
        )

    colunas: dict[str, pd.Series] = {}
    nomes: dict[str, str] = {}
    for cod in lista:
        meta = _serie_meta(cod)
        s = transform.to_monthly(_carregar(cod, inicio, fim))
        # normaliza para início do mês p/ alinhar IPCA (1º dia) vs diárias (fim)
        s.index = s.index.to_period("M").to_timestamp()
        colunas[str(cod)] = s
        nomes[str(cod)] = meta.nome

    # DataFrame a partir de um dict de Series alinha pelo índice (outer join).
    df = pd.DataFrame(colunas).sort_index()
    pontos = [
        PontoComparacao(
            data=idx.date().isoformat(),
            valores={
                k: (float(v) if pd.notna(v) else None) for k, v in row.items()
            },
        )
        for idx, row in df.iterrows()
    ]
    return ComparacaoResponse(codigos=lista, nomes=nomes, n=len(pontos), pontos=pontos)


@app.get("/indicadores/juro-real", response_model=JuroRealResponse, tags=["indicadores"])
def juro_real(
    inicio: str | None = Query(None, examples=["01/01/2020"]),
    fim: str | None = None,
):
    """Juro real ex-post (Selic meta vs. IPCA 12m) pela equação de Fisher."""
    selic = _carregar(COD_SELIC_META, inicio, fim)
    ipca = _carregar(COD_IPCA, inicio, fim)

    df = transform.real_interest(selic, ipca)
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail="Sem sobreposição suficiente entre Selic e IPCA no período.",
        )

    serie_pts = [
        PontoJuroReal(
            data=idx.date().isoformat(),
            selic=float(r.selic),
            ipca_12m=float(r.ipca_12m),
            juro_real=float(r.juro_real),
        )
        for idx, r in df.iterrows()
    ]
    return JuroRealResponse(
        fonte_selic=f"SGS {COD_SELIC_META} ({SERIES[COD_SELIC_META].nome})",
        fonte_ipca=f"SGS {COD_IPCA} ({SERIES[COD_IPCA].nome})",
        n=len(serie_pts),
        ultimo=serie_pts[-1],
        serie=serie_pts,
    )


@app.get("/indicadores/{codigo}/resumo", response_model=ResumoResponse, tags=["indicadores"])
def resumo(
    codigo: int,
    inicio: str | None = Query(None, examples=["01/01/2020"]),
    fim: str | None = None,
):
    """Último valor, variação MoM/YoY, média móvel 12m, mín/máx na janela."""
    meta = _serie_meta(codigo)
    s = _carregar(codigo, inicio, fim)
    dados = transform.summary(s, JANELA_MOVEL)
    return ResumoResponse(codigo=codigo, nome=meta.nome, **dados)


@app.get("/indicadores/{codigo}/qualidade", response_model=QualidadeResponse, tags=["indicadores"])
def qualidade(
    codigo: int,
    inicio: str | None = Query(None, examples=["01/01/2020"]),
    fim: str | None = None,
):
    """Relatório de qualidade: % faltante, freshness e lacunas detectadas."""
    meta = _serie_meta(codigo)
    s = _carregar(codigo, inicio, fim)

    if meta.frequencia == "mensal":
        relatorio = transform.quality_report(s, freq="M", max_dias_lacuna=35)
    else:
        relatorio = transform.quality_report(s, freq="B", max_dias_lacuna=5)

    relatorio["lacunas"] = [Lacuna(**g) for g in relatorio["lacunas"]]
    return QualidadeResponse(codigo=codigo, nome=meta.nome, **relatorio)
