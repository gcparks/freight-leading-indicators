"""
Statistical analysis module for the Freight Leading Indicators project.

Implements:
  1. Seasonal decomposition (STL) of core freight metrics
  2. Cross-correlation analysis at multiple lags
  3. Granger causality testing
  4. Regime detection (Hidden Markov Model)
  5. Multivariate regression with interpretable coefficients

All analysis functions read from DuckDB and return structured results
that feed into the report renderer.

Usage:
    python -m src.analysis.analyze
"""

import json
import logging
import warnings
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import signal, stats
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=FutureWarning)

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "lane_health.duckdb"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


def get_connection():
    return duckdb.connect(str(DB_PATH), read_only=True)


# ═══════════════════════════════════════════════════════════════════
# PART 1: Seasonal Decomposition
# ═══════════════════════════════════════════════════════════════════

def seasonal_decomposition(series: pd.Series, period: int = 52) -> dict:
    """
    Perform STL decomposition on a time series.

    Args:
        series: Time series with DatetimeIndex
        period: Seasonal period (52 for weekly, 12 for monthly)

    Returns:
        Dict with trend, seasonal, residual components and diagnostics
    """
    # STL requires no missing values
    series = series.interpolate(method="linear").dropna()

    if len(series) < period * 2:
        logger.warning(f"Series too short for STL ({len(series)} < {period * 2})")
        return {"status": "insufficient_data"}

    stl = STL(series, period=period, robust=True)
    result = stl.fit()

    # Compute strength of seasonality and trend
    var_resid = np.var(result.resid)
    var_resid_seasonal = np.var(result.resid + result.seasonal)
    var_resid_trend = np.var(result.resid + result.trend)

    seasonal_strength = max(0, 1 - var_resid / var_resid_seasonal)
    trend_strength = max(0, 1 - var_resid / var_resid_trend)

    return {
        "status": "ok",
        "trend": result.trend,
        "seasonal": result.seasonal,
        "residual": result.resid,
        "seasonal_strength": round(seasonal_strength, 4),
        "trend_strength": round(trend_strength, 4),
        "n_observations": len(series),
    }


def decompose_fred_series(con, series_id: str) -> dict:
    """Run STL on a specific FRED series from the database."""
    df = con.execute(f"""
        SELECT date, value FROM fred_series
        WHERE series_id = '{series_id}'
        ORDER BY date
    """).fetchdf()

    if df.empty:
        return {"series_id": series_id, "status": "no_data"}

    df["date"] = pd.to_datetime(df["date"])
    ts = df.set_index("date")["value"]

    # Determine period based on data frequency
    avg_gap = ts.index.to_series().diff().median().days
    period = 52 if avg_gap < 14 else 12

    result = seasonal_decomposition(ts, period=period)
    result["series_id"] = series_id
    return result


# ═══════════════════════════════════════════════════════════════════
# PART 2: Cross-Correlation & Granger Causality
# ═══════════════════════════════════════════════════════════════════

def compute_cross_correlation(
    target: pd.Series,
    predictor: pd.Series,
    max_lag: int = 12,
) -> dict:
    """
    Compute cross-correlation between two aligned time series
    at lags from 0 to max_lag.

    Positive lag means the predictor LEADS the target.

    Returns:
        Dict with lag values, correlations, and optimal lag
    """
    # Align on common dates
    combined = pd.concat([target.rename("target"), predictor.rename("predictor")], axis=1).dropna()

    if len(combined) < max_lag + 10:
        return {"status": "insufficient_overlap", "n": len(combined)}

    # Standardize
    t = (combined["target"] - combined["target"].mean()) / combined["target"].std()
    p = (combined["predictor"] - combined["predictor"].mean()) / combined["predictor"].std()

    correlations = {}
    for lag in range(0, max_lag + 1):
        if lag == 0:
            corr = t.corr(p)
        else:
            corr = t.iloc[lag:].reset_index(drop=True).corr(
                p.iloc[:-lag].reset_index(drop=True)
            )
        correlations[lag] = round(corr, 4) if not np.isnan(corr) else None

    # Find optimal lag (highest absolute correlation)
    valid = {k: v for k, v in correlations.items() if v is not None}
    if valid:
        optimal_lag = max(valid, key=lambda k: abs(valid[k]))
        optimal_corr = valid[optimal_lag]
    else:
        optimal_lag = None
        optimal_corr = None

    return {
        "status": "ok",
        "correlations": correlations,
        "optimal_lag": optimal_lag,
        "optimal_correlation": optimal_corr,
        "n_observations": len(combined),
    }


def run_granger_test(
    target: pd.Series,
    predictor: pd.Series,
    max_lag: int = 8,
) -> dict:
    """
    Run Granger causality test: does the predictor help predict the target
    beyond what the target's own history provides?

    Returns:
        Dict with F-statistics and p-values by lag, and overall conclusion
    """
    combined = pd.concat([target.rename("target"), predictor.rename("predictor")], axis=1).dropna()

    if len(combined) < max_lag + 20:
        return {"status": "insufficient_data", "n": len(combined)}

    # Stationarity check — Granger requires stationary series
    adf_target = adfuller(combined["target"], autolag="AIC")
    adf_predictor = adfuller(combined["predictor"], autolag="AIC")

    # If non-stationary, difference the series
    target_diffed = False
    predictor_diffed = False

    if adf_target[1] > 0.05:
        combined["target"] = combined["target"].diff()
        target_diffed = True
    if adf_predictor[1] > 0.05:
        combined["predictor"] = combined["predictor"].diff()
        predictor_diffed = True

    combined = combined.dropna()

    if len(combined) < max_lag + 20:
        return {"status": "insufficient_data_after_differencing"}

    try:
        results = grangercausalitytests(combined[["target", "predictor"]], maxlag=max_lag, verbose=False)
    except Exception as e:
        return {"status": "error", "message": str(e)}

    lag_results = {}
    min_p = 1.0
    best_lag = None

    for lag in range(1, max_lag + 1):
        if lag in results:
            test_result = results[lag]
            f_stat = test_result[0]["ssr_ftest"][0]
            p_value = test_result[0]["ssr_ftest"][1]
            lag_results[lag] = {
                "f_statistic": round(f_stat, 4),
                "p_value": round(p_value, 6),
                "significant_05": p_value < 0.05,
                "significant_01": p_value < 0.01,
            }
            if p_value < min_p:
                min_p = p_value
                best_lag = lag

    return {
        "status": "ok",
        "target_differenced": target_diffed,
        "predictor_differenced": predictor_diffed,
        "lag_results": lag_results,
        "best_lag": best_lag,
        "best_p_value": round(min_p, 6),
        "granger_causes": min_p < 0.05,
        "n_observations": len(combined),
    }


# ═══════════════════════════════════════════════════════════════════
# PART 3: Regime Detection
# ═══════════════════════════════════════════════════════════════════

def detect_regimes(series: pd.Series, n_states: int = 2) -> dict:
    """
    Fit a Hidden Markov Model to detect freight market regimes
    (e.g., loose vs. tight).

    Args:
        series: Rate or rate-change time series
        n_states: Number of hidden states (default 2: loose/tight)

    Returns:
        Dict with state assignments, transition matrix, and state means
    """
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        return {"status": "hmmlearn_not_installed"}

    clean = series.dropna().values.reshape(-1, 1)

    if len(clean) < 50:
        return {"status": "insufficient_data"}

    model = GaussianHMM(
        n_components=n_states,
        covariance_type="full",
        n_iter=200,
        random_state=42,
    )

    model.fit(clean)
    states = model.predict(clean)

    # Sort states by mean so state 0 = lower mean (loose), state 1 = higher (tight)
    state_means = model.means_.flatten()
    sort_idx = np.argsort(state_means)
    state_map = {old: new for new, old in enumerate(sort_idx)}
    states = np.array([state_map[s] for s in states])

    return {
        "status": "ok",
        "state_means": [round(model.means_[i][0], 4) for i in sort_idx],
        "state_labels": ["Loose" if i == 0 else "Tight" for i in range(n_states)],
        "transition_matrix": np.round(model.transmat_[np.ix_(sort_idx, sort_idx)], 4).tolist(),
        "current_state": int(states[-1]),
        "current_label": "Loose" if states[-1] == 0 else "Tight",
        "state_sequence": states.tolist(),
        "n_observations": len(clean),
        "log_likelihood": round(model.score(clean), 2),
    }


# ═══════════════════════════════════════════════════════════════════
# PART 4: Multivariate Regression
# ═══════════════════════════════════════════════════════════════════

def build_predictive_model(
    target: pd.Series,
    predictors: dict[str, pd.Series],
    lags: dict[str, int],
) -> dict:
    """
    Build an OLS regression predicting the target from lagged predictors.

    Args:
        target: Dependent variable (e.g., week-over-week rate change)
        predictors: Dict of {name: series} for independent variables
        lags: Dict of {name: optimal_lag_weeks} from cross-correlation

    Returns:
        Dict with coefficients, R², diagnostics
    """
    # Build lagged feature matrix
    features = pd.DataFrame(index=target.index)

    for name, series in predictors.items():
        lag = lags.get(name, 0)
        if lag > 0:
            features[name] = series.shift(lag)
        else:
            features[name] = series

    # Combine and drop NAs
    combined = pd.concat([target.rename("target"), features], axis=1).dropna()

    if len(combined) < len(predictors) * 5 + 10:
        return {"status": "insufficient_data", "n": len(combined)}

    y = combined["target"]
    X = add_constant(combined.drop(columns=["target"]))

    model = OLS(y, X).fit()

    # Extract coefficients with confidence intervals
    coefficients = []
    for var in model.params.index:
        coefficients.append({
            "variable": var,
            "coefficient": round(model.params[var], 6),
            "std_error": round(model.bse[var], 6),
            "t_stat": round(model.tvalues[var], 4),
            "p_value": round(model.pvalues[var], 6),
            "significant": model.pvalues[var] < 0.05,
            "ci_lower": round(model.conf_int().loc[var, 0], 6),
            "ci_upper": round(model.conf_int().loc[var, 1], 6),
        })

    return {
        "status": "ok",
        "r_squared": round(model.rsquared, 4),
        "adj_r_squared": round(model.rsquared_adj, 4),
        "f_statistic": round(model.fvalue, 4),
        "f_p_value": round(model.f_pvalue, 6),
        "aic": round(model.aic, 2),
        "bic": round(model.bic, 2),
        "durbin_watson": round(float(model.resid.autocorr()), 4),
        "n_observations": int(model.nobs),
        "coefficients": coefficients,
    }


# ═══════════════════════════════════════════════════════════════════
# ORCHESTRATOR: Run Full Analysis
# ═══════════════════════════════════════════════════════════════════

# Corrected FRED series IDs for leading indicator pairs
# Format: (predictor_series_id, target_series_id, description)
LEADING_INDICATOR_PAIRS = [
    # Manufacturing signals → Trucking costs
    ("NOFDFSA066MSFRBPHI", "PCU484121484121", "Philly Fed Future New Orders → TL Trucking PPI"),
    ("VNWOSAMFRBDAL", "PCU484121484121", "Dallas Fed New Orders → TL Trucking PPI"),
    ("DGORDER", "PCU484121484121", "Durable Goods Orders → TL Trucking PPI"),
    ("DTCDFSA066MSFRBPHI", "PCU484121484121", "Philly Fed Delivery Times → TL Trucking PPI"),
    ("DTMSAMFRBDAL", "PCU484121484121", "Dallas Fed Delivery Times → TL Trucking PPI"),

    # Demand signals → Trucking costs
    ("RETAILIRSA", "PCU484121484121", "Retail Inv/Sales Ratio → TL Trucking PPI"),
    ("UMCSENT", "PCU484121484121", "Consumer Sentiment → TL Trucking PPI"),
    ("PCE", "PCU484121484121", "Personal Consumption → TL Trucking PPI"),

    # Energy signals → Diesel prices
    ("IPG32411S", "GASDESW", "Refinery Production Index → Diesel Price"),

    # Demand signals → Freight volume
    ("RETAILIRSA", "TSIFRGHT", "Retail Inv/Sales → Freight TSI"),
    ("UMCSENT", "TSIFRGHT", "Consumer Sentiment → Freight TSI"),
    ("PCE", "TSIFRGHT", "Personal Consumption → Freight TSI"),
    ("DGORDER", "TSIFRGHT", "Durable Goods Orders → Freight TSI"),

    # Freight volume → Trucking costs (does volume lead price?)
    ("TSIFRGHT", "PCU484121484121", "Freight TSI → TL Trucking PPI"),
    ("TSIFRGHT", "PCU484122484122", "Freight TSI → LTL Trucking PPI"),

    # Diesel → Trucking costs (cost pass-through lag)
    ("GASDESW", "PCU484121484121", "Diesel Price → TL Trucking PPI"),
    ("GASDESW", "PCU484122484122", "Diesel Price → LTL Trucking PPI"),

    # Cross-mode: LTL vs TL
    ("PCU484121484121", "PCU484122484122", "TL Trucking PPI → LTL Trucking PPI"),
]


def load_fred_as_series(con, series_id: str) -> pd.Series:
    """Load a FRED series from DuckDB as a pandas Series with DatetimeIndex."""
    df = con.execute(f"""
        SELECT date, value FROM fred_series
        WHERE series_id = '{series_id}'
        ORDER BY date
    """).fetchdf()
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["value"]


def run_full_analysis() -> dict:
    """
    Run the complete analysis pipeline and return structured results.
    """
    con = get_connection()
    results = {
        "run_date": str(date.today()),
        "generated_at": datetime.now().isoformat(),
    }

    # ── Check what data we have ──
    available = con.execute("""
        SELECT series_id, COUNT(*) as n, MIN(date) as first_date, MAX(date) as last_date
        FROM fred_series
        GROUP BY series_id
        ORDER BY series_id
    """).fetchdf()
    logger.info(f"Available FRED series:\n{available.to_string()}")
    results["data_inventory"] = available.to_dict(orient="records")

    # ── Part 1: Seasonal Decomposition ──
    logger.info("Part 1: Seasonal Decomposition")
    decompositions = {}
    for series_id in ["GASDESW", "PCU484121484121", "PCU484122484122", "TSIFRGHT"]:
        logger.info(f"  Decomposing {series_id}")
        result = decompose_fred_series(con, series_id)
        # Store summary (not the full arrays)
        decompositions[series_id] = {
            k: v for k, v in result.items()
            if k not in ("trend", "seasonal", "residual")
        }
    results["decompositions"] = decompositions

    # ── Part 2: Cross-Correlation & Granger Causality ──
    logger.info("Part 2: Cross-Correlation & Granger Causality")
    correlations = []
    granger_results = []

    # Get set of available series for filtering
    available_ids = set(available["series_id"].tolist()) if not available.empty else set()

    for predictor_id, target_id, description in LEADING_INDICATOR_PAIRS:
        # Skip pairs where we don't have data
        if predictor_id not in available_ids or target_id not in available_ids:
            logger.info(f"  Skipping (missing data): {description}")
            continue

        logger.info(f"  Testing: {description}")

        predictor = load_fred_as_series(con, predictor_id)
        target = load_fred_as_series(con, target_id)

        if predictor.empty or target.empty:
            logger.warning(f"    Empty series for {predictor_id} or {target_id}")
            continue

        # Align frequencies — resample monthly series to match weekly if needed
        if len(predictor) < len(target) / 3:
            predictor = predictor.resample("W").ffill()
        elif len(target) < len(predictor) / 3:
            target = target.resample("W").ffill()

        # Cross-correlation
        xcorr = compute_cross_correlation(target, predictor, max_lag=12)
        xcorr["predictor"] = predictor_id
        xcorr["target"] = target_id
        xcorr["description"] = description
        correlations.append(xcorr)

        # Granger causality
        gc = run_granger_test(target, predictor, max_lag=8)
        gc["predictor"] = predictor_id
        gc["target"] = target_id
        gc["description"] = description
        granger_results.append(gc)

    results["cross_correlations"] = correlations
    results["granger_causality"] = granger_results

    # Summarize significant Granger results
    significant_causes = [
        {
            "description": gc["description"],
            "best_lag": gc.get("best_lag"),
            "p_value": gc.get("best_p_value"),
        }
        for gc in granger_results
        if gc.get("granger_causes")
    ]
    results["significant_leading_indicators"] = significant_causes
    logger.info(f"  Found {len(significant_causes)} significant Granger-causal relationships")

    # Summarize strongest cross-correlations
    strong_correlations = [
        {
            "description": xc["description"],
            "optimal_lag": xc.get("optimal_lag"),
            "correlation": xc.get("optimal_correlation"),
        }
        for xc in correlations
        if xc.get("status") == "ok"
        and xc.get("optimal_correlation") is not None
        and abs(xc["optimal_correlation"]) > 0.3
    ]
    strong_correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    results["strongest_correlations"] = strong_correlations
    logger.info(f"  Found {len(strong_correlations)} strong cross-correlations (|r| > 0.3)")

    # ── Part 3: Regime Detection ──
    logger.info("Part 3: Regime Detection")
    trucking_ppi = load_fred_as_series(con, "PCU484121484121")
    if not trucking_ppi.empty:
        # Use rate of change for regime detection
        trucking_roc = trucking_ppi.pct_change().dropna()
        regime_result = detect_regimes(trucking_roc)
        results["regime_detection"] = regime_result
    else:
        results["regime_detection"] = {"status": "no_data"}

    # ── Part 4: Build predictive model if we have enough significant predictors ──
    logger.info("Part 4: Predictive Model")
    if len(significant_causes) >= 2:
        # Use the significant Granger-causal predictors
        target_series = load_fred_as_series(con, "PCU484121484121")  # TL Trucking PPI
        if not target_series.empty:
            target_roc = target_series.pct_change().dropna()

            pred_dict = {}
            lag_dict = {}
            for sc in significant_causes:
                # Extract predictor ID from description
                for pid, tid, desc in LEADING_INDICATOR_PAIRS:
                    if desc == sc["description"] and tid == "PCU484121484121":
                        pred_series = load_fred_as_series(con, pid)
                        if not pred_series.empty:
                            pred_roc = pred_series.pct_change().dropna()
                            # Align to weekly
                            if len(pred_roc) < len(target_roc) / 3:
                                pred_roc = pred_roc.resample("W").ffill()
                            pred_dict[pid] = pred_roc
                            lag_dict[pid] = sc.get("best_lag", 1)
                        break

            if len(pred_dict) >= 2:
                model_result = build_predictive_model(target_roc, pred_dict, lag_dict)
                results["predictive_model"] = model_result
            else:
                results["predictive_model"] = {"status": "insufficient_significant_predictors"}
        else:
            results["predictive_model"] = {"status": "no_target_data"}
    else:
        results["predictive_model"] = {
            "status": "insufficient_significant_predictors",
            "note": f"Only {len(significant_causes)} significant Granger relationships found, need >= 2"
        }

    con.close()

    # ── Save Results ──
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / f"analysis_{date.today()}.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Analysis results saved: {output_path}")

    return results


if __name__ == "__main__":
    results = run_full_analysis()

    # Print summary
    print("\n" + "=" * 70)
    print("FREIGHT LEADING INDICATORS — ANALYSIS SUMMARY")
    print("=" * 70)

    # Data inventory
    inv = results.get("data_inventory", [])
    print(f"\nData: {len(inv)} FRED series loaded")
    for s in inv:
        print(f"  {s['series_id']:30s}  {s['n']:>4} obs  ({s['first_date']} → {s['last_date']})")

    # Decomposition
    print("\nSeasonal Decomposition:")
    for sid, decomp in results.get("decompositions", {}).items():
        if decomp.get("status") == "ok":
            print(f"  {sid}: trend_strength={decomp['trend_strength']}, "
                  f"seasonal_strength={decomp['seasonal_strength']}, "
                  f"n={decomp['n_observations']}")
        else:
            print(f"  {sid}: {decomp.get('status', 'unknown')}")

    # Strongest correlations
    print("\nStrongest Cross-Correlations (|r| > 0.3):")
    for sc in results.get("strongest_correlations", []):
        print(f"  {sc['description']:55s}  r={sc['correlation']:+.4f}  lag={sc['optimal_lag']}")
    if not results.get("strongest_correlations"):
        print("  None found")

    # Granger causality
    print("\nSignificant Leading Indicators (Granger causality, p < 0.05):")
    for ind in results.get("significant_leading_indicators", []):
        print(f"  ✓ {ind['description']:55s}  lag={ind['best_lag']}  p={ind['p_value']:.6f}")
    if not results.get("significant_leading_indicators"):
        print("  None found — may need more historical data")

    # Regime detection
    regime = results.get("regime_detection", {})
    if regime.get("status") == "ok":
        print(f"\nFreight Market Regime: {regime['current_label']}")
        print(f"  State means: {regime['state_means']}")
        print(f"  Transition matrix: {regime['transition_matrix']}")
    elif regime.get("status") == "hmmlearn_not_installed":
        print("\nRegime detection: install hmmlearn (pip install hmmlearn)")
    else:
        print(f"\nRegime detection: {regime.get('status', 'unknown')}")

    # Predictive model
    model = results.get("predictive_model", {})
    if model.get("status") == "ok":
        print(f"\nPredictive Model (OLS):")
        print(f"  R² = {model['r_squared']}, Adj R² = {model['adj_r_squared']}")
        print(f"  F = {model['f_statistic']}, p = {model['f_p_value']:.6f}")
        print(f"  n = {model['n_observations']}")
        print(f"  Coefficients:")
        for coef in model["coefficients"]:
            sig = "*" if coef["significant"] else " "
            print(f"    {sig} {coef['variable']:30s}  β={coef['coefficient']:+.6f}  "
                  f"t={coef['t_stat']:+.4f}  p={coef['p_value']:.4f}")
    else:
        print(f"\nPredictive model: {model.get('status', 'unknown')}")
        if model.get("note"):
            print(f"  {model['note']}")

    print()
