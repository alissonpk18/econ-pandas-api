"""Schemas Pydantic das respostas — alimentam a validação e o Swagger (/docs)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Resposta do endpoint GET /health (liveness check)."""

    status: str = "ok"
    servico: str = "indicadores-economicos-api"


class Ponto(BaseModel):
    """Um ponto da série temporal: data em formato ISO e valor numérico."""

    data: str = Field(..., examples=["2024-01-31"])
    valor: float


class SerieResponse(BaseModel):
    """Resposta de GET /series/{codigo} — série completa tratada."""

    codigo: int
    nome: str
    unidade: str
    inicio: str | None = None  # data do primeiro ponto (ISO)
    fim: str | None = None     # data do último ponto (ISO)
    n: int                     # total de pontos retornados
    pontos: list[Ponto]


class ResumoResponse(BaseModel):
    """Resposta de GET /indicadores/{codigo}/resumo.

    Variações em fração: 0.012 representa 1,2%. None indica dados insuficientes
    (ex.: YoY requer ao menos 13 meses de histórico mensal).
    """

    codigo: int
    nome: str
    ultimo_valor: float | None
    data_ultimo: str | None
    variacao_mom: float | None = Field(None, description="fração; 0.012 = 1,2%")
    variacao_yoy: float | None = Field(None, description="fração; 0.045 = 4,5%")
    media_movel_12m: float | None
    minimo: float | None
    maximo: float | None


class PontoComparacao(BaseModel):
    """Um mês do endpoint GET /indicadores/comparar.

    `valores` é um dict cujas chaves são os códigos SGS como string (ex. "11"),
    para compatibilidade com JSON onde chaves de objeto devem ser string.
    None indica que a série não tem dado para aquele mês (outer join).
    """

    data: str
    valores: dict[str, float | None] = Field(
        ..., description="valor de cada código no mês, ex.: {'11': 11.75, '433': 0.4}"
    )


class ComparacaoResponse(BaseModel):
    """Resposta de GET /indicadores/comparar — múltiplas séries alinhadas por data."""

    codigos: list[int]
    nomes: dict[str, str]   # ex.: {"11": "Selic", "433": "IPCA"}
    n: int
    pontos: list[PontoComparacao]


class PontoJuroReal(BaseModel):
    """Um mês do cálculo de juro real pela equação de Fisher."""

    data: str
    selic: float = Field(..., description="taxa nominal anualizada (% a.a.)")
    ipca_12m: float = Field(..., description="inflação acumulada em 12 meses (%)")
    juro_real: float = Field(..., description="juro real ex-post (% a.a.)")


class JuroRealResponse(BaseModel):
    """Resposta de GET /indicadores/juro-real.

    Requer ao menos 13 meses de IPCA para acumular a janela de 12m da Fisher.
    """

    metodo: str = "Fisher: ((1+Selic)/(1+IPCA_12m) - 1) * 100"
    fonte_selic: str
    fonte_ipca: str
    n: int
    ultimo: PontoJuroReal | None  # None quando não há sobreposição suficiente
    serie: list[PontoJuroReal]


class Lacuna(BaseModel):
    """Intervalo sem dados detectado por detect_gaps."""

    de: str   # data anterior ao buraco (ISO)
    ate: str  # data posterior ao buraco (ISO)
    dias: int # duração da lacuna em dias corridos


class QualidadeResponse(BaseModel):
    """Resposta de GET /indicadores/{codigo}/qualidade."""

    codigo: int
    nome: str
    total_pontos: int
    inicio: str | None
    fim: str | None
    pct_faltante: float | None = Field(None, description="% de períodos ausentes vs. grade esperada")
    ultima_atualizacao: str | None
    defasagem_dias: int | None = Field(None, description="dias desde a última observação até hoje")
    lacunas: list[Lacuna]
