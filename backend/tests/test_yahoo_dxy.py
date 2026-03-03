import importlib.util
import sys
import types
from datetime import datetime, timedelta

import pandas as pd


def load_module(path, name="yahoo_data"):
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


def make_hist(dates, closes):
    idx = pd.to_datetime(dates)
    return pd.DataFrame({"Close": closes}, index=idx)


def test_dxy_no_tickers_uses_snapshot(tmp_path, monkeypatch):
    # Prepare module path
    mod_path = tmp_path.joinpath("yahoo_data.py")
    repo_path = (tmp_path / "repo")
    repo_path.mkdir()
    # We'll load the real file from the repo
    import os
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".." , ".."))
    yahoo_path = os.path.join(repo_root, "data_fetchers", "yahoo_data.py")

    yahoo = load_module(yahoo_path, name="test_yahoo_data_no_tickers")

    # Monkeypatch yfinance behavior: all tickers return empty history
    def fake_ticker_ctor(sym):
        return FakeTicker(sym, {})

    yahoo.yf = types.SimpleNamespace(Ticker=fake_ticker_ctor)

    # Inject a storage.db.get_latest_snapshots that returns a recent snapshot
    def fake_get_latest_snapshots(n):
        return [{
            "dxy_value": 99.5,
            "timestamp": datetime.now().isoformat()
        }]

    sys.modules["storage.db"] = types.SimpleNamespace(get_latest_snapshots=fake_get_latest_snapshots)

    # Ensure fallback is enabled and age threshold generous
    yahoo.USE_LAST_SNAPSHOT_FOR_FALLBACK = True
    yahoo.FALLBACK_MAX_SNAPSHOT_AGE_HOURS = 48

    res = yahoo.get_dxy_data(timeframe="current")
    assert res.get("_fallback") is True
    assert float(res.get("current_price")) == 99.5


def test_dxy_validation_and_fred_fallback(monkeypatch):
    import os
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".." , ".."))
    yahoo_path = os.path.join(repo_root, "data_fetchers", "yahoo_data.py")
    yahoo = load_module(yahoo_path, name="test_yahoo_data_validation")

    # Build histograms: primary symbol DX-Y.NYB has price 100, alt DX=F has price 120
    primary_hist = make_hist([
        (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        datetime.now().strftime("%Y-%m-%d")
    ], [95.0, 100.0])

    alt_hist = make_hist([
        (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        datetime.now().strftime("%Y-%m-%d")
    ], [115.0, 120.0])

    data_map = {"DX-Y.NYB": primary_hist, "DX=F": alt_hist}

    def fake_ticker_ctor(sym):
        return FakeTicker(sym, data_map)

    yahoo.yf = types.SimpleNamespace(Ticker=fake_ticker_ctor)

    # Monkeypatch FRED fallback to return a usable value
    fred_module = types.SimpleNamespace(get_fred_series=lambda series_id, timeframe=None: {"value": "101.5", "date": datetime.now().strftime("%Y-%m-%d")})
    sys.modules["backend.data_fetchers.fred_data"] = fred_module

    # Ensure tolerance is small so validation fails
    yahoo.DXY_VALIDATION_TOLERANCE_PCT = 0.05

    res = yahoo.get_dxy_data(timeframe="current")
    # Validation should mark suspect and fallback should switch source to FRED
    assert res.get("_suspect") is True
    assert res.get("source") == "FRED"
    assert float(res.get("current_price")) == round(101.5, 2)
