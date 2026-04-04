import importlib.util
import os
import sys
import types

import pandas as pd


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeTicker:
    def __init__(self, symbol, data_map):
        self.symbol = symbol
        self._data_map = data_map

    def history(self, period="1d"):
        df = self._data_map.get(self.symbol)
        if df is None:
            return pd.DataFrame()
        return df


def make_fred_df(values, dates=None):
    if dates is None:
        dates = pd.to_datetime(["2026-03-20", "2026-03-27"])
    return pd.DataFrame({"date": pd.to_datetime(dates), "value": values})


def backend_path(*parts):
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(backend_root, *parts)


def fake_fred_module(series_values):
    def get_fred_data(series_id, start_date=None, timeframe="current", sort_order="asc"):
        return make_fred_df(series_values)

    return types.SimpleNamespace(
        get_fred_data=get_fred_data,
        _fred_observation_on_or_before_months_ago=lambda df, months: df.iloc[0],
        _fred_observation_on_or_before_calendar_days_ago=lambda df, days: df.iloc[0],
    )


def test_sp500_uses_fred_fallback_instead_of_etf_scale(monkeypatch):
    yahoo = load_module(backend_path("data_fetchers", "yahoo_data.py"), "test_yahoo_sp500_fallback")
    yahoo.yf = types.SimpleNamespace(Ticker=lambda sym: FakeTicker(sym, {}))
    pkg = types.ModuleType("data_fetchers")
    pkg.fred_data = fake_fred_module([5800.0, 5900.0])
    monkeypatch.setitem(sys.modules, "data_fetchers", pkg)

    res = yahoo.get_sp500_data(timeframe="week")

    assert res.get("source") == "FRED:SP500"
    assert float(res.get("current_price")) == 5900.0
    assert float(res.get("change")) == round((5900.0 - 5800.0) / 5800.0 * 100, 2)


def test_vix_uses_fred_fallback_instead_of_vixy_scale(monkeypatch):
    yahoo = load_module(backend_path("data_fetchers", "yahoo_data.py"), "test_yahoo_vix_fallback")
    yahoo.yf = types.SimpleNamespace(Ticker=lambda sym: FakeTicker(sym, {}))
    pkg = types.ModuleType("data_fetchers")
    pkg.fred_data = fake_fred_module([22.5, 27.25])
    monkeypatch.setitem(sys.modules, "data_fetchers", pkg)

    res = yahoo.get_vix_data(timeframe="week")

    assert res.get("source") == "FRED:VIXCLS"
    assert float(res.get("current_value")) == 27.25
    assert float(res.get("change")) == 4.75
    assert res.get("level") == "high"


def test_dxy_uses_exact_fx_basket_before_proxy(monkeypatch):
    yahoo = load_module(backend_path("data_fetchers", "yahoo_data.py"), "test_yahoo_dxy_fx_basket")
    yahoo.STRICT_LIVE_OFFICIAL_ONLY = False

    dates = pd.to_datetime(["2026-03-26", "2026-03-27"])
    data_map = {
        "DX-Y.NYB": pd.DataFrame(),
        "DX=F": pd.DataFrame(),
        "DXY": pd.DataFrame(),
        "EURUSD=X": pd.DataFrame({"Close": [1.07, 1.08]}, index=dates),
        "JPY=X": pd.DataFrame({"Close": [149.0, 150.0]}, index=dates),
        "GBPUSD=X": pd.DataFrame({"Close": [1.26, 1.27]}, index=dates),
        "CAD=X": pd.DataFrame({"Close": [1.34, 1.35]}, index=dates),
        "SEK=X": pd.DataFrame({"Close": [10.4, 10.5]}, index=dates),
        "CHF=X": pd.DataFrame({"Close": [0.87, 0.88]}, index=dates),
    }
    yahoo.yf = types.SimpleNamespace(Ticker=lambda sym: FakeTicker(sym, data_map))
    yahoo.USE_LAST_SNAPSHOT_FOR_FALLBACK = False

    res = yahoo.get_dxy_data(timeframe="current")

    expected = 50.14348112
    expected *= 1.08 ** -0.576
    expected *= 150.0 ** 0.136
    expected *= 1.27 ** -0.119
    expected *= 1.35 ** 0.091
    expected *= 10.5 ** 0.042
    expected *= 0.88 ** 0.036

    assert res.get("source") == "fx_basket_formula"
    assert res.get("_fallback") is True
    assert abs(float(res.get("current_price")) - round(expected, 2)) < 1e-9


def test_dxy_strict_mode_prefers_ecb_basket(monkeypatch):
    yahoo = load_module(backend_path("data_fetchers", "yahoo_data.py"), "test_yahoo_dxy_ecb_strict")
    yahoo.STRICT_LIVE_OFFICIAL_ONLY = True
    monkeypatch.setattr(
        yahoo,
        "_dxy_from_ecb_fx_basket",
        lambda timeframe: {
            "current_price": 101.23,
            "change": -0.4,
            "date": "2026-03-27",
            "data_as_of": "2026-03-27",
            "comparison_date": "2026-02-27",
            "source": "ECB:EXR_fx_basket",
            "timeframe": timeframe,
        },
    )

    res = yahoo.get_dxy_data("month")

    assert res["source"] == "ECB:EXR_fx_basket"
    assert res["current_price"] == 101.23


def test_dxy_structure_strict_mode_uses_ecb_history(monkeypatch):
    yahoo = load_module(backend_path("data_fetchers", "yahoo_data.py"), "test_yahoo_dxy_structure_ecb")
    yahoo.STRICT_LIVE_OFFICIAL_ONLY = True
    idx = pd.date_range("2026-01-01", periods=30, freq="B")
    closes = [100, 103, 101, 105, 102, 107, 104, 109, 106, 111, 108, 113, 110, 115, 112, 117, 114, 119, 116, 121, 118, 123, 120, 125, 122, 127, 124, 129, 126, 131]
    monkeypatch.setattr(
        yahoo,
        "_ecb_dxy_history",
        lambda timeframe, lookback_days=None: pd.DataFrame({"Close": closes}, index=idx),
    )

    res = yahoo.get_dxy_structure("month")

    assert res["structure"] != "unknown"
    assert res["source"] == "ECB:EXR_fx_basket"


def test_gold_strict_mode_uses_lbma_official_feed(monkeypatch):
    yahoo = load_module(backend_path("data_fetchers", "yahoo_data.py"), "test_yahoo_gold_lbma")
    yahoo.STRICT_LIVE_OFFICIAL_ONLY = True
    monkeypatch.setattr(
        yahoo,
        "_lbma_gold_data",
        lambda timeframe: {
            "current_price": 3012.4,
            "date": "2026-03-27",
            "data_as_of": "2026-03-27",
            "comparison_date": "26/3",
            "change": 1.2,
            "change_label": "1D",
            "change_unit": "percent",
            "trend": "rising",
            "timeframe": timeframe,
            "source": "LBMA:today.json",
        },
    )

    res = yahoo.get_gold_data("current")

    assert res["source"] == "LBMA:today.json"
    assert res["current_price"] == 3012.4


def test_gold_strict_month_augmented_with_yahoo_when_lbma_has_no_1m_change(monkeypatch):
    """LBMA today.json only has ~1 week of history; 1M % must come from futures."""
    yahoo = load_module(backend_path("data_fetchers", "yahoo_data.py"), "test_yahoo_gold_lbma_month")
    yahoo.STRICT_LIVE_OFFICIAL_ONLY = True
    monkeypatch.setattr(
        yahoo,
        "_lbma_gold_data",
        lambda timeframe: {
            "current_price": 4529.15,
            "date": "2026-03-30",
            "data_as_of": "2026-03-30",
            "comparison_date": None,
            "change": None,
            "change_label": "1M",
            "change_unit": "percent",
            "trend": "stable",
            "timeframe": timeframe,
            "source": "LBMA:today.json",
        },
    )
    monkeypatch.setattr(
        yahoo,
        "_yahoo_gold_futures_rolling_change",
        lambda tf: {
            "symbol": "GC=F",
            "change": 1.4,
            "comparison_date": "2026-02-27",
            "change_label": "1M",
            "trend": "rising",
        },
    )

    res = yahoo.get_gold_data("month")

    assert res["current_price"] == 4529.15
    assert res["change"] == 1.4
    assert res["comparison_date"] == "2026-02-27"
    assert "LBMA" in res["source"]
    assert "GC=F" in res["source"]


def test_gold_strict_month_fred_when_yahoo_augment_fails(monkeypatch):
    yahoo = load_module(backend_path("data_fetchers", "yahoo_data.py"), "test_yahoo_gold_lbma_fred")
    yahoo.STRICT_LIVE_OFFICIAL_ONLY = True
    monkeypatch.setattr(
        yahoo,
        "_lbma_gold_data",
        lambda timeframe: {
            "current_price": 4529.15,
            "date": "2026-03-30",
            "data_as_of": "2026-03-30",
            "comparison_date": None,
            "change": None,
            "change_label": "1M",
            "change_unit": "percent",
            "trend": "stable",
            "timeframe": timeframe,
            "source": "LBMA:today.json",
        },
    )
    monkeypatch.setattr(yahoo, "_yahoo_gold_futures_rolling_change", lambda tf: None)
    monkeypatch.setattr(
        yahoo,
        "_fred_gold_month_percent_lbma_augment",
        lambda: {
            "symbol": "FRED:GOLDAMGBD228NLBM",
            "change": 3.3,
            "comparison_date": "2026-02-27",
            "change_label": "1M",
            "trend": "rising",
        },
    )

    res = yahoo.get_gold_data("month")

    assert res["change"] == 3.3
    assert "FRED:GOLDAMGBD228NLBM" in res["source"]
    assert res["current_price"] == 4529.15


def test_emerging_markets_prefers_eem(monkeypatch):
    yahoo = load_module(backend_path("data_fetchers", "yahoo_data.py"), "test_yahoo_eem")
    dates = pd.to_datetime(["2026-03-20", "2026-03-27"])
    data_map = {
        "EEM": pd.DataFrame({"Close": [10.0, 10.5]}, index=dates),
    }
    yahoo.yf = types.SimpleNamespace(Ticker=lambda sym: FakeTicker(sym, data_map))

    res = yahoo.get_emerging_markets_data("week")

    assert res["source"] == "EEM"
    assert res["current_price"] == 10.5


def test_stablecoin_snapshot_fallback_keeps_total_only(monkeypatch):
    cg = load_module(backend_path("data_fetchers", "coingecko_data.py"), "test_coingecko_snapshot_stables")
    monkeypatch.setattr(cg, "_get_global_market_payload", lambda: None)
    monkeypatch.setattr(cg, "_coinlore_global_market_payload", lambda: None)
    monkeypatch.setattr(cg, "_coinlore_top_tickers", lambda limit=100: [])
    monkeypatch.setattr(cg, "_snapshot_stable_dom", lambda: 8.7)

    res = cg.get_stablecoin_data(timeframe="current")

    assert res.get("total_stablecoin_dominance") == 8.7
    assert res.get("usdt_dominance") is None
    assert res.get("usdc_dominance") is None
    assert res.get("source") == "last_snapshot"


def test_btc_dominance_returns_error_when_all_sources_missing(monkeypatch):
    cg = load_module(backend_path("data_fetchers", "coingecko_data.py"), "test_coingecko_btc_dom_missing")
    monkeypatch.setattr(cg, "_get_global_market_payload", lambda: None)
    monkeypatch.setattr(cg, "_coinlore_global_market_payload", lambda: None)
    monkeypatch.setattr(cg, "_snapshot_btc_dominance", lambda: None)

    res = cg.get_btc_dominance(timeframe="current")

    assert res.get("error") == "BTC dominance unavailable"
    assert "btc_dominance" not in res


def test_btc_ohlcv_200d_uses_true_200_day_window(monkeypatch):
    cg = load_module(backend_path("data_fetchers", "coingecko_data.py"), "test_coingecko_btc_ma200")
    monkeypatch.setattr(cg, "_coinbase_btc_daily_closes", lambda limit=400: [])
    monkeypatch.setattr(cg, "_kraken_btc_daily_closes", lambda limit=400: [])

    fake_yahoo = types.SimpleNamespace(get_btc_ma200_vol_from_yahoo=lambda: {"error": "unavailable"})
    pkg = types.ModuleType("data_fetchers")
    pkg.yahoo_data = fake_yahoo
    monkeypatch.setitem(sys.modules, "data_fetchers", pkg)

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    klines = []
    for day in range(400):
        close = day + 1
        klines.append([day, "0", "0", "0", str(close), "0", 0, "0", 0, "0", "0", "0"])

    monkeypatch.setattr(cg.requests, "get", lambda *args, **kwargs: FakeResponse(klines))

    res = cg.get_btc_ohlcv_200d()

    assert res.get("source") == "binance_public"
    assert res.get("days_of_data") == 400
    assert res.get("ma200") == 300.5


def test_btc_spot_coinbase_uses_public_candles(monkeypatch):
    cg = load_module(backend_path("data_fetchers", "coingecko_data.py"), "test_coingecko_coinbase_btc")
    monkeypatch.setattr(cg, "_coinbase_btc_daily_closes", lambda limit=120: [100.0 + i for i in range(40)])

    res = cg.get_btc_spot_coinbase("month")

    assert res["price_usd"] == 139.0
    assert res["_source"] == "coinbase_exchange"
    assert "change" in res


def test_btc_ohlcv_200d_prefers_coinbase_first_party(monkeypatch):
    cg = load_module(backend_path("data_fetchers", "coingecko_data.py"), "test_coingecko_coinbase_ma200")
    monkeypatch.setattr(cg, "_coinbase_btc_daily_closes", lambda limit=400: [float(i) for i in range(1, 401)])

    res = cg.get_btc_ohlcv_200d()

    assert res["source"] == "coinbase_exchange"
    assert res["days_of_data"] == 400
    assert res["ma200"] == 300.5
