"""Cliente HTTP para o SGS (Sistema Gerenciador de Séries Temporais) do BCB.

Endpoint público, sem autenticação:

    https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados
        ?formato=json&dataInicial=01/01/2020[&dataFinal=...]

Inclui um cache simples em memória com TTL para não martelar o SGS em
chamadas repetidas (os dados mudam, no máximo, uma vez por dia).
"""
from __future__ import annotations

import time

import httpx

from .config import DATA_INICIAL_PADRAO

BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
TIMEOUT = httpx.Timeout(15.0)

# Cache em memória: chave (codigo, inicio, fim) -> (timestamp, dados).
_CACHE: dict[tuple, tuple[float, list[dict]]] = {}
_CACHE_TTL = 60 * 30  # 30 minutos


class BCBError(RuntimeError):
    """Falha ao consultar o SGS (rede, status HTTP ou JSON inválido)."""


def fetch_serie(
    codigo: int,
    inicio: str | None = None,
    fim: str | None = None,
) -> list[dict]:
    """Busca os dados crus de uma série no SGS.

    Datas no formato ``dd/mm/aaaa`` (exigência do SGS). Devolve a lista de
    dicts ``{"data": ..., "valor": ...}`` exatamente como o SGS retorna —
    a limpeza fica a cargo de :func:`app.transform.parse_sgs`.
    """
    chave = (codigo, inicio, fim)
    agora = time.time()

    em_cache = _CACHE.get(chave)
    if em_cache is not None and (agora - em_cache[0]) < _CACHE_TTL:
        return em_cache[1]

    params = {"formato": "json", "dataInicial": inicio or DATA_INICIAL_PADRAO}
    if fim:
        params["dataFinal"] = fim

    url = BASE_URL.format(codigo=codigo)
    try:
        resp = httpx.get(
            url,
            params=params,
            timeout=TIMEOUT,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        dados = resp.json()
    except httpx.HTTPStatusError as exc:
        raise BCBError(
            f"SGS retornou HTTP {exc.response.status_code} para a série {codigo}."
        ) from exc
    except httpx.HTTPError as exc:
        raise BCBError(
            f"Falha de rede ao consultar a série {codigo}: {exc}"
        ) from exc
    except ValueError as exc:  # JSON inválido
        raise BCBError(
            f"Resposta do SGS não é JSON válido para a série {codigo}."
        ) from exc

    if not isinstance(dados, list):
        raise BCBError(f"Formato inesperado do SGS para a série {codigo}.")

    _CACHE[chave] = (agora, dados)
    return dados


def limpar_cache() -> None:
    """Esvazia o cache em memória (útil em testes)."""
    _CACHE.clear()
