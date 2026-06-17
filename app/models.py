"""Schemas Pydantic das respostas — alimentam a validação e o Swagger (/docs)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    servico: str = "indicadores-economicos-api"


class Ponto(BaseModel):
    data: str = Field(..., examples=["2024-01-31"])
    valor: float


class SerieResponse(BaseModel):
    codigo: int
    nome: str
    unidade: str
    inicio: str | None = None
    fim: str | None = None
    n: int
    pontos: list[Ponto]


class ResumoResponse(BaseModel):
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
    data: str
    valores: dict[str, float | None] = Field(
        ..., description="valor de cada código no mês, ex.: {'11': 11.75, '433': 0.4}"
    )


class ComparacaoResponse(BaseModel):
    codigos: list[int]
    nomes: dict[str, str]
    n: int
    pontos: list[PontoComparacao]


class PontoJuroReal(BaseModel):
    data: str
    selic: float = Field(..., description="taxa nominal anualizada (% a.a.)")
    ipca_12m: float = Field(..., description="inflação acumulada em 12 meses (%)")
    juro_real: float = Field(..., description="juro real ex-post (% a.a.)")


class JuroRealResponse(BaseModel):
    metodo: str = "Fisher: ((1+Selic)/(1+IPCA_12m) - 1) * 100"
    fonte_selic: str
    fonte_ipca: str
    n: int
    ultimo: PontoJuroReal | None
    serie: list[PontoJuroReal]


class Lacuna(BaseModel):
    de: str
    ate: str
    dias: int


class QualidadeResponse(BaseModel):
    codigo: int
    nome: str
    total_pontos: int
    inicio: str | None
    fim: str | None
    pct_faltante: float | None = Field(None, description="% de períodos ausentes")
    ultima_atualizacao: str | None
    defasagem_dias: int | None = Field(None, description="dias desde a última observação")
    lacunas: list[Lacuna]
