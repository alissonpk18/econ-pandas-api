"""Testes das funções Pandas — todos offline (sem rede).

A ideia é provar o núcleo analítico: parsing de dados "sujos", mensalização,
variações MoM/YoY, média móvel, merge, juro real e qualidade de dados.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app import bcb_client, transform


# --------------------------------------------------------------------------- #
# parse_sgs
# --------------------------------------------------------------------------- #
def test_parse_sgs_basico_ordena_e_tipa():
    registros = [
        {"data": "01/03/2020", "valor": "4.50"},
        {"data": "01/01/2020", "valor": "3.10"},
        {"data": "01/02/2020", "valor": "3.90"},
    ]
    s = transform.parse_sgs(registros)

    assert len(s) == 3
    assert s.index.is_monotonic_increasing
    assert s.index[0] == pd.Timestamp("2020-01-01")
    assert s.iloc[0] == pytest.approx(3.10)
    assert s.index.name == "data"
    assert s.name == "valor"
    assert str(s.dtype) == "float64"


def test_parse_sgs_vazio():
    s = transform.parse_sgs([])
    assert s.empty
    assert str(s.dtype) == "float64"


def test_parse_sgs_descarta_invalidos():
    registros = [
        {"data": "01/01/2020", "valor": "3.10"},
        {"data": "data-ruim", "valor": "9.99"},   # data inválida -> descarta
        {"data": "01/02/2020", "valor": "x"},      # valor inválido -> descarta
    ]
    s = transform.parse_sgs(registros)
    assert len(s) == 1
    assert s.iloc[0] == pytest.approx(3.10)


# --------------------------------------------------------------------------- #
# reamostragem / variações
# --------------------------------------------------------------------------- #
def test_to_monthly_pega_ultimo_do_mes():
    idx = pd.date_range("2023-01-01", periods=40, freq="D")
    s = pd.Series(range(40), index=idx, dtype="float64")
    mensal = transform.to_monthly(s)

    assert len(mensal) == 2
    assert mensal.iloc[0] == 30.0   # último dia de janeiro (2023-01-31)
    assert mensal.iloc[1] == 39.0   # último ponto disponível em fevereiro


def test_variacoes_e_media_movel():
    idx = pd.date_range("2023-01-31", periods=14, freq="ME")
    s = pd.Series(range(10, 24), index=idx, dtype="float64")  # 10..23

    assert transform.mom_change(s).iloc[-1] == pytest.approx(1 / 22)
    assert transform.yoy_change(s).iloc[-1] == pytest.approx(12 / 11)
    assert transform.rolling_mean(s, 12).iloc[-1] == pytest.approx(17.5)


def test_inflacao_acumulada():
    ipca = pd.Series([1.0, 1.0, 1.0])  # 1% ao mês
    acc = transform.accumulated_inflation(ipca)
    assert acc.iloc[-1] == pytest.approx(1.030301)  # 1.01**3


# --------------------------------------------------------------------------- #
# merge / alinhamento
# --------------------------------------------------------------------------- #
def test_merge_series_outer_expoe_desalinhamento():
    a = pd.Series(
        [1.0, 2.0, 3.0],
        index=pd.to_datetime(["2023-01-01", "2023-02-01", "2023-03-01"]),
    )
    b = pd.Series(
        [10.0, 20.0],
        index=pd.to_datetime(["2023-02-01", "2023-03-01"]),
    )
    df = transform.merge_series(a, b, "a", "b")

    assert df.shape == (3, 2)
    assert list(df.columns) == ["a", "b"]
    assert pd.isna(df.loc[pd.Timestamp("2023-01-01"), "b"])
    assert df.loc[pd.Timestamp("2023-02-01"), "b"] == 10.0


# --------------------------------------------------------------------------- #
# qualidade de dados
# --------------------------------------------------------------------------- #
def test_detect_gaps_encontra_mes_faltante():
    idx = pd.to_datetime(["2023-01-31", "2023-02-28", "2023-04-30", "2023-05-31"])
    s = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx)  # março ausente

    lacunas = transform.detect_gaps(s, max_dias=35)
    assert len(lacunas) == 1
    assert lacunas[0]["de"] == "2023-02-28"
    assert lacunas[0]["ate"] == "2023-04-30"
    assert lacunas[0]["dias"] == 61


def test_quality_report_mensal():
    idx = pd.to_datetime(["2023-01-31", "2023-02-28", "2023-04-30", "2023-05-31"])
    s = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx)  # março ausente

    rel = transform.quality_report(s, freq="M")
    assert rel["total_pontos"] == 4
    assert rel["inicio"] == "2023-01-31"
    assert rel["fim"] == "2023-05-31"
    assert rel["pct_faltante"] == 20.0  # 1 mês ausente em 5 esperados
    assert len(rel["lacunas"]) == 1


def test_quality_report_serie_vazia():
    rel = transform.quality_report(transform.parse_sgs([]))
    assert rel["total_pontos"] == 0
    assert rel["pct_faltante"] is None
    assert rel["lacunas"] == []


# --------------------------------------------------------------------------- #
# indicadores derivados
# --------------------------------------------------------------------------- #
def test_summary():
    idx = pd.date_range("2023-01-31", periods=14, freq="ME")
    s = pd.Series(range(10, 24), index=idx, dtype="float64")  # 10..23

    r = transform.summary(s, janela=12)
    assert r["ultimo_valor"] == 23.0
    assert r["data_ultimo"] == "2024-02-29"
    assert r["variacao_mom"] == pytest.approx(1 / 22)
    assert r["variacao_yoy"] == pytest.approx(12 / 11)
    assert r["media_movel_12m"] == pytest.approx(17.5)
    assert r["minimo"] == 10.0
    assert r["maximo"] == 23.0


def test_real_interest_fisher():
    # IPCA de 1% ao mês por 13 meses -> 12m acumulado = 1.01**12 ~ 12.6825%
    ipca = pd.Series(
        [1.0] * 13,
        index=pd.date_range("2020-01-01", periods=13, freq="MS"),
    )
    # Selic meta constante de 13% a.a. (série diária).
    selic = pd.Series(
        13.0,
        index=pd.date_range("2020-01-01", "2021-01-31", freq="D"),
    )

    df = transform.real_interest(selic, ipca)

    # Só os 2 meses com janela de 12m completa sobrevivem ao dropna.
    assert len(df) == 2
    assert df["selic"].iloc[-1] == pytest.approx(13.0)
    assert df["ipca_12m"].iloc[-1] == pytest.approx(12.6825, abs=1e-2)
    # (1.13 / 1.126825 - 1) * 100 ~ 0.2818
    assert df["juro_real"].iloc[-1] == pytest.approx(0.2818, abs=1e-2)


# --------------------------------------------------------------------------- #
# cliente SGS (sem rede, via monkeypatch) — exercita parsing + cache
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_fetch_serie_usa_cache(monkeypatch):
    bcb_client.limpar_cache()
    chamadas = {"n": 0}

    def fake_get(url, params=None, timeout=None, headers=None):
        chamadas["n"] += 1
        return _FakeResp([{"data": "01/01/2020", "valor": "4.50"}])

    monkeypatch.setattr(bcb_client.httpx, "get", fake_get)

    primeira = bcb_client.fetch_serie(433)
    segunda = bcb_client.fetch_serie(433)  # deve vir do cache

    assert primeira == segunda
    assert chamadas["n"] == 1  # a segunda chamada não tocou a "rede"
    # e o parsing transforma isso numa Series limpa:
    s = transform.parse_sgs(primeira)
    assert s.iloc[0] == pytest.approx(4.50)
