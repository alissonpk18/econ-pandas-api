"""Configuração central: catálogo de séries do SGS e constantes do projeto.

Os códigos abaixo seguem o catálogo do Sistema Gerenciador de Séries Temporais
(SGS) do Banco Central. Atenção a variações importantes:

  - Selic tem 'meta' (cód. 432, % a.a., definida pelo Copom) e 'efetiva diária'
    (cód. 11, % a.d.). Para juro real usamos a META, que já é anualizada.
  - IPCA (cód. 433) é a variação mensal em %; o nível/índice é o 433 acumulado.

Sempre confirme um código no catálogo oficial antes de fixar:
https://www3.bcb.gov.br/sgspub/localizarseries/localizarSeries.do
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Serie:
    """Metadados de uma série do SGS."""

    codigo: int
    nome: str
    unidade: str
    frequencia: str  # "mensal" | "diaria"
    descricao: str = ""


# Catálogo das séries expostas pela API.
SERIES: dict[int, Serie] = {
    433: Serie(433, "IPCA", "% a.m.", "mensal",
               "Índice de Preços ao Consumidor Amplo — variação mensal"),
    11: Serie(11, "Selic", "% a.d.", "diaria",
              "Taxa de juros — Selic efetiva diária"),
    432: Serie(432, "Selic Meta", "% a.a.", "diaria",
               "Meta da taxa Selic definida pelo Copom"),
    12: Serie(12, "CDI", "% a.d.", "diaria",
              "Taxa de juros — CDI/DI diário"),
    1: Serie(1, "Dólar", "R$/US$", "diaria",
             "Taxa de câmbio — Dólar (PTAX venda)"),
}

# Data inicial padrão para fetch (formato dd/mm/aaaa exigido pelo SGS).
DATA_INICIAL_PADRAO = "01/01/2020"

# Janela padrão (em meses) para média móvel e estatísticas de resumo.
JANELA_MOVEL = 12

# Códigos usados no cálculo de juro real (ex-post, equação de Fisher).
COD_SELIC_META = 432  # juro nominal anualizado (% a.a.)
COD_IPCA = 433        # inflação mensal -> acumulada em 12 meses
