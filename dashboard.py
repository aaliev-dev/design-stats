#!/usr/bin/env python3
"""
Streamlit dashboard for Jira Design task insights.
Run: streamlit run dashboard.py

Features:
- Overview: KPI cards, throughput (with rolling MA), status/project breakdown
- Cycle Time & Flow: percentiles (P50/P75/P90), CFD, Sankey flow, bottleneck
- People: assignee workload, heatmap, time logging, worklog coverage
- Deep Dives: worklog coverage, time in backlog, stale WIP, rework, estimation accuracy
- Data Explorer: multi-select filters, date range, searchable table
"""
import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime, timedelta
import bisect

DB_PATH = Path(__file__).parent / "design_insights.db"

st.set_page_config(
    page_title="Jira Design Insights",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Hide ALL Streamlit chrome (Deploy, hamburger menu, footer, "Made with Streamlit")
# and disable keyboard shortcuts ('c' = clear cache, 'r' = rerun, 's' = settings)
st.markdown("""
<style>
    /* Hide Deploy button */
    [data-testid="stDeployButton"] { display: none !important; }
    /* Hide hamburger Main menu */
    [data-testid="stMainMenu"] { display: none !important; }
    /* Hide stToolbar contents but keep it in render tree (so stExpandSidebarButton survives) */
    [data-testid="stToolbar"] {
        max-height: 0 !important;
        overflow: visible !important;
        pointer-events: none !important;
    }
    footer { display: none !important; }
    /* Hide keyboard shortcut hints and capture dialog */
    [data-testid="stStatusWidget"] { display: none !important; }
    [data-testid="stToolbarContent"] { display: none !important; }
    /* Remove default top padding */
    .block-container { padding-top: 1rem !important; }

    /* ============================================================
       SIDEBAR EXPAND BUTTON — always visible on-screen.
       Streamlit's stExpandSidebarButton lives inside stToolbar
       (which collapses to height:0). We make it position:fixed so
       it escapes the collapsed parent and stays clickable.
       No JS needed — this is Streamlit's native button with its
       native click handler.
       ============================================================ */
    [data-testid="stExpandSidebarButton"] {
        position: fixed !important;
        left: 8px !important;
        top: 8px !important;
        z-index: 999999 !important;
        width: 36px !important;
        height: 36px !important;
        border-radius: 6px !important;
        border: 1px solid rgba(128,128,128,0.3) !important;
        background: rgba(255,255,255,0.95) !important;
        pointer-events: auto !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.15) !important;
    }
    [data-testid="stExpandSidebarButton"] svg {
        color: #555 !important;
        width: 20px !important;
        height: 20px !important;
    }
    @media (prefers-color-scheme: dark) {
        [data-testid="stExpandSidebarButton"] {
            background: rgba(40,40,40,0.95) !important;
            border-color: rgba(128,128,128,0.4) !important;
        }
        [data-testid="stExpandSidebarButton"] svg {
            color: #ccc !important;
        }
    }

    /* ============================================================
       ПРАВИЛО ВНУТРЕННЕГО/ВНЕШНЕГО ОТСТУПА (Law of Proximity)
       Внутри группы — тесно (малый padding), между группами —
       просторно (большой margin). Это создаёт визуальную
       группировку: заголовок + описание + график воспринимаются
       как единый блок, а следующий блок чётко отделён.
       ============================================================ */

    /* --- ВНЕШНИЙ отступ: между секциями (большой) --- */

    /* h2: начало крупной секции. Большой отступ сверху =
       визуальное разделение между секциями. */
    h2 {
        margin-top: 3rem !important;
        margin-bottom: 0.3rem !important;
        padding-top: 0.5rem;
    }

    /* h3: начало подсекции. Средний отступ сверху =
       отделение от предыдущего графика/блока. */
    h3 {
        margin-top: 2.2rem !important;
        margin-bottom: 0.2rem !important;
    }

    /* Горизонтальная черта (---) = явный разделитель секций.
       Дополнительный воздух сверху и снизу. */
    hr {
        margin-top: 2.5rem !important;
        margin-bottom: 1rem !important;
        border: none;
        border-top: 1px solid rgba(128, 128, 128, 0.2);
    }

    /* --- ВНУТРЕННИЙ отступ: внутри группы (малый) --- */

    /* Caption (описание) сразу под заголовком: прижать вплотную,
       т.к. это часть той же группы. */
    [data-testid="stCaptionContainer"] {
        margin-top: 0.1rem !important;
        margin-bottom: 0.6rem !important;
    }

    /* Метрики внутри группы: компактнее, т.к. относятся к
       одному заголовку. */
    [data-testid="stMetric"] {
        margin-top: 0.2rem !important;
    }

    /* Графики: лёгкий отступ снизу внутри группы, но не
       слишком большой — следующий элемент может быть частью
       той же секции. */
    .stPlotlyChart, [data-testid="stPlotlyChart"] {
        margin-top: 0.3rem !important;
        margin-bottom: 0.4rem !important;
    }

    /* Таблицы данных: компактно внутри группы. */
    [data-testid="stDataFrame"] {
        margin-top: 0.3rem !important;
    }

    /* --- Tab заголовки --- */
    /* Заголовок страницы (h1): без лишнего отступа сверху. */
    h1 {
        margin-top: 0 !important;
        margin-bottom: 0.3rem !important;
    }

    /* --- Column containers: равномерное распределение --- */
    [data-testid="stHorizontalBlock"] {
        gap: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# Disable Streamlit keyboard shortcuts ('c'=clear cache, 'r'=rerun, 's'=settings)
# Use st.html() for the script injection
st.html("""
<script>
    document.addEventListener('keydown', function(e) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        var k = e.key.toLowerCase();
        if (k === 'c' || k === 'r' || k === 's') {
            e.stopPropagation();
            e.preventDefault();
        }
    }, true);
</script>
""")

# ============================================================
#  DATA LOADING
# ============================================================

@st.cache_resource
def get_conn():
    if not DB_PATH.exists():
        st.error(f"Database not found: {DB_PATH}. Run `python3 fetch_data.py` first.")
        st.stop()
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


@st.cache_data(ttl=60)
def load_issues():
    return pd.read_sql("SELECT * FROM issues", get_conn())


@st.cache_data(ttl=60)
def load_transitions():
    df = pd.read_sql("SELECT * FROM status_transitions", get_conn())
    df["transition_epoch"] = pd.to_numeric(df["transition_epoch"], errors="coerce")
    return df.dropna(subset=["transition_epoch"])


@st.cache_data(ttl=60)
def load_worklogs():
    return pd.read_sql("SELECT * FROM worklogs", get_conn())


@st.cache_data(ttl=60)
def load_changelog():
    df = pd.read_sql("SELECT * FROM changelog", get_conn())
    df["created_epoch"] = pd.to_numeric(df["created_epoch"], errors="coerce")
    return df


# ============================================================
#  HELPER FUNCTIONS
# ============================================================

def get_status_map(df_issues):
    """Build status→category mapping."""
    return dict(zip(df_issues["status"], df_issues["status_category"]))


def categorize(status, smap):
    """Get category for a status, with heuristics for unknowns."""
    if pd.isna(status):
        return "To Do"
    s = str(status)
    if s in smap:
        return smap[s]
    sl = s.lower()
    if any(x in sl for x in ["done", "resolved", "closed", "cancel"]):
        return "Done"
    if any(x in sl for x in ["progress", "review", "development", "clarif"]):
        return "In Progress"
    return "To Do"


def _build_cat_cache(df_issues, df_trans=None):
    """Pre-compute category for all unique statuses to avoid repeated string ops.

    Returns a dict mapping status_string -> category.
    Handles None/NaN by returning "To Do" for missing keys.
    """
    smap = get_status_map(df_issues)
    statuses = set(df_issues["status"].dropna().unique().tolist())
    if df_trans is not None:
        statuses.update(df_trans["from_status"].dropna().unique().tolist())
        statuses.update(df_trans["to_status"].dropna().unique().tolist())
    cat_cache = {}
    for s in statuses:
        cat_cache[str(s)] = categorize(s, smap)
    return cat_cache


CAT_ORDER = {"To Do": 0, "In Progress": 1, "Done": 2}


def safe_pct(series, p):
    """Safe percentile on positive values."""
    clean = series.dropna()
    clean = clean[clean > 0]
    return np.percentile(clean, p) if len(clean) > 0 else 0


@st.cache_data(ttl=120)
def build_cfd(df_issues: pd.DataFrame, df_trans: pd.DataFrame):
    """Build Cumulative Flow Diagram data: monthly counts per status category."""
    smap = get_status_map(df_issues)
    dfi = _precompute_epochs(df_issues)

    # Per-issue timeline: (epochs_list, cats_list)
    timelines = {}
    for key, group in df_trans.groupby("issue_key"):
        group = group.sort_values("transition_epoch")
        rows = dfi[dfi["key"] == key]
        if len(rows) == 0 or pd.isna(rows.iloc[0].get("created_epoch")):
            continue
        ce = rows.iloc[0]["created_epoch"]
        eps = [ce]
        cats = [categorize(group.iloc[0]["from_status"], smap)]
        for _, r in group.iterrows():
            ep = r["transition_epoch"]
            c = categorize(r["to_status"], smap)
            if ep is not None and ep > eps[-1]:
                eps.append(ep)
                cats.append(c)
        timelines[key] = (eps, cats)

    # Issues with no transitions
    for _, row in dfi.iterrows():
        if row["key"] not in timelines and pd.notna(row.get("created_epoch")):
            timelines[row["key"]] = (
                [row["created_epoch"]],
                [categorize(row.get("status"), smap)],
            )

    end_date = datetime.now().strftime("%Y-%m-%d")
    months = pd.date_range(start="2018-01-31", end=end_date, freq="ME")
    records = []
    for m in months:
        me = m.timestamp()
        td = ip = dn = 0
        for eps, cats in timelines.values():
            if eps[0] > me:
                continue
            idx = bisect.bisect_right(eps, me) - 1
            c = cats[max(idx, 0)]
            if c == "To Do":
                td += 1
            elif c == "In Progress":
                ip += 1
            elif c == "Done":
                dn += 1
        records.append({"month": m.strftime("%Y-%m"),
                         "To Do": td, "In Progress": ip, "Done": dn})
    return pd.DataFrame(records)


def _precompute_epochs(df_issues):
    """Add created_epoch and resolved_epoch columns to df_issues (vectorized)."""
    dfi = df_issues.copy()
    created_ts = pd.to_datetime(dfi["created"], errors="coerce")
    resolved_ts = pd.to_datetime(dfi["resolution_date"], errors="coerce")
    # Force nanosecond resolution: pandas 2.x defaults to datetime64[us]
    # (microseconds), so .astype("int64") gives microseconds, not nanoseconds.
    # Without this, dividing by 1e9 makes epochs 1000x too small.
    created_ns = created_ts.astype("datetime64[ns]")
    resolved_ns = resolved_ts.astype("datetime64[ns]")
    dfi["created_epoch"] = created_ns.astype("int64").where(created_ns.notna()) / 1e9
    dfi["resolved_epoch"] = resolved_ns.astype("int64").where(resolved_ns.notna()) / 1e9
    return dfi


def _group_transitions(df_trans):
    """Pre-group transitions by issue_key into dict of (epoch, from_status, to_status) tuples.

    This avoids O(n*m) DataFrame filtering inside per-issue loops.
    """
    groups = {}
    sorted_trans = df_trans.sort_values("transition_epoch")
    for key, grp in sorted_trans.groupby("issue_key"):
        groups[key] = list(zip(
            grp["transition_epoch"].tolist(),
            grp["from_status"].tolist(),
            grp["to_status"].tolist(),
        ))
    return groups


def calc_time_in_backlog(df_issues, df_trans):
    """Time each issue spent in To Do status (days)."""
    cat_cache = _build_cat_cache(df_issues, df_trans)
    dfi = _precompute_epochs(df_issues)
    now_ep = datetime.now().timestamp()
    trans_groups = _group_transitions(df_trans)

    # Convert to lists for fast iteration (avoids iterrows() overhead)
    keys = dfi["key"].tolist()
    created_epochs = dfi["created_epoch"].tolist()
    resolved_epochs = dfi["resolved_epoch"].tolist()
    statuses = dfi["status"].tolist()
    TODO = "To Do"

    results = []
    for i in range(len(keys)):
        key = keys[i]
        ce = created_epochs[i]
        if ce is None or pd.isna(ce):
            continue
        re = resolved_epochs[i]
        end_ep = re if (re is not None and not pd.isna(re)) else now_ep
        trans_list = trans_groups.get(key, [])

        if len(trans_list) == 0:
            cat = cat_cache.get(str(statuses[i]) if statuses[i] is not None else "", TODO)
            bl = end_ep - ce if cat == TODO else None
        else:
            bl = 0
            prev_ep = ce
            prev_cat = cat_cache.get(str(trans_list[0][1]), TODO)
            for ep_val, _from_s, to_s in trans_list:
                cat = cat_cache.get(str(to_s), TODO)
                if prev_cat == TODO and ep_val is not None:
                    bl += ep_val - prev_ep
                if ep_val is not None:
                    prev_ep = ep_val
                prev_cat = cat
            if prev_cat == TODO:
                bl += end_ep - prev_ep

        results.append({"key": key,
                          "backlog_days": bl / 86400 if bl is not None and bl > 0 else None})
    return pd.DataFrame(results)


def calc_time_in_progress(df_issues, df_trans):
    """Time each issue spent in In Progress status category (days)."""
    cat_cache = _build_cat_cache(df_issues, df_trans)
    dfi = _precompute_epochs(df_issues)
    now_ep = datetime.now().timestamp()
    trans_groups = _group_transitions(df_trans)

    # Convert to lists for fast iteration (avoids iterrows() overhead)
    keys = dfi["key"].tolist()
    created_epochs = dfi["created_epoch"].tolist()
    resolved_epochs = dfi["resolved_epoch"].tolist()
    statuses = dfi["status"].tolist()
    IP = "In Progress"
    TODO = "To Do"

    results = []
    for i in range(len(keys)):
        key = keys[i]
        ce = created_epochs[i]
        if ce is None or pd.isna(ce):
            continue
        re = resolved_epochs[i]
        end_ep = re if (re is not None and not pd.isna(re)) else now_ep
        trans_list = trans_groups.get(key, [])

        if len(trans_list) == 0:
            cat = cat_cache.get(str(statuses[i]) if statuses[i] is not None else "", TODO)
            ip = end_ep - ce if cat == IP else None
        else:
            ip = 0
            prev_ep = ce
            prev_cat = cat_cache.get(str(trans_list[0][1]), TODO)
            for ep_val, _from_s, to_s in trans_list:
                cat = cat_cache.get(str(to_s), TODO)
                if prev_cat == IP and ep_val is not None:
                    ip += ep_val - prev_ep
                if ep_val is not None:
                    prev_ep = ep_val
                prev_cat = cat
            if prev_cat == IP:
                ip += end_ep - prev_ep

        results.append({"key": key,
                          "in_progress_days": ip / 86400 if ip is not None and ip > 0 else None})
    return pd.DataFrame(results)


def calc_time_in_status(df_issues, df_trans, target_statuses):
    """Time each issue spent in a specific status or set of statuses (days).

    Unlike calc_time_in_progress (which works on categories), this checks
    exact status names — e.g. ['In Review', 'In review (Design)'].
    Returns DataFrame with columns: key, status_days, status_name.
    If multiple target statuses are given, the status_name column indicates
    which one the issue was last in among the targets.
    """
    targets = set(target_statuses)
    dfi = _precompute_epochs(df_issues)
    now_ep = datetime.now().timestamp()
    trans_groups = _group_transitions(df_trans)

    # Convert to lists for fast iteration
    keys = dfi["key"].tolist()
    created_epochs = dfi["created_epoch"].tolist()
    resolved_epochs = dfi["resolved_epoch"].tolist()
    statuses = dfi["status"].tolist()

    results = []
    for i in range(len(keys)):
        key = keys[i]
        ce = created_epochs[i]
        if ce is None or pd.isna(ce):
            continue
        re = resolved_epochs[i]
        end_ep = re if (re is not None and not pd.isna(re)) else now_ep
        trans_list = trans_groups.get(key, [])
        last_status = str(statuses[i]) if statuses[i] is not None else ""

        if len(trans_list) == 0:
            if last_status in targets:
                results.append({"key": key, "status_days": (end_ep - ce) / 86400,
                                "status_name": last_status})
            continue

        total_in_target = 0
        matched_status = None
        prev_ep = ce
        prev_status = str(trans_list[0][1])
        for ep_val, _from_s, to_s in trans_list:
            if prev_status in targets and ep_val is not None and ep_val > prev_ep:
                total_in_target += ep_val - prev_ep
                matched_status = prev_status
            if ep_val is not None:
                prev_ep = ep_val
            prev_status = str(to_s)

        # If currently in a target status, add time from last transition to now/resolved
        if str(prev_status) in targets:
            total_in_target += end_ep - prev_ep
            matched_status = str(prev_status)

        if total_in_target > 0:
            results.append({"key": key, "status_days": total_in_target / 86400,
                            "status_name": matched_status})

    return pd.DataFrame(results)


def calc_review_time_trend(df_issues, df_trans, target_statuses, label):
    """Monthly median time in a specific status (days)."""
    res = calc_time_in_status(df_issues, df_trans, target_statuses)
    if len(res) == 0:
        return res
    merged = res.merge(df_issues[["key", "resolution_date"]], on="key", how="left")
    resolved = merged[merged["resolution_date"].notna()].copy()
    if len(resolved) == 0:
        return pd.DataFrame()
    resolved["ym"] = pd.to_datetime(resolved["resolution_date"], errors="coerce").dt.to_period("M").astype(str)
    monthly = resolved.groupby("ym").agg(
        median_days=("status_days", "median"),
        mean_days=("status_days", "mean"),
        count=("key", "count"),
    ).reset_index()
    monthly = monthly[monthly["count"] >= 3].sort_values("ym")
    monthly["median_ma"] = monthly["median_days"].rolling(3, min_periods=1).mean()
    return monthly


def calc_review_time_per_person(df_issues, df_trans, target_statuses):
    """Median time in specific status per assignee (days)."""
    res = calc_time_in_status(df_issues, df_trans, target_statuses)
    if len(res) == 0:
        return pd.DataFrame()
    merged = res.merge(df_issues[["key", "assignee_name"]], on="key", how="left")
    merged = merged[merged["assignee_name"].notna()]
    if len(merged) == 0:
        return pd.DataFrame()
    per_person = merged.groupby("assignee_name").agg(
        median_days=("status_days", "median"),
        mean_days=("status_days", "mean"),
        count=("key", "count"),
    ).reset_index()
    per_person = per_person[per_person["count"] >= 3]
    return per_person.sort_values("median_days", ascending=True)


def calc_rework(df_trans, smap):
    """Count issues with backward transitions (rework)."""
    rework = set()
    total = 0
    for key, group in df_trans.groupby("issue_key"):
        group = group.sort_values("transition_epoch")
        total += 1
        prev_cat = categorize(group.iloc[0]["from_status"], smap)
        for _, r in group.iterrows():
            curr_cat = categorize(r["to_status"], smap)
            if CAT_ORDER.get(curr_cat, 0) < CAT_ORDER.get(prev_cat, 0):
                rework.add(key)
                break
            prev_cat = curr_cat
    return len(rework), total


def calc_stale(df_issues, df_trans):
    """Days since last transition for non-Done issues.

    Issues with no transitions use creation date as fallback —
    these are tasks that were created but never moved, potentially
    the most stale of all.
    """
    now_ep = datetime.now().timestamp()
    last_t = df_trans.groupby("issue_key")["transition_epoch"].max()
    df_nd = df_issues[df_issues["status_category"] != "Done"].copy()
    df_nd["last_transition"] = df_nd["key"].map(last_t)
    # Fallback: issues with no transitions use created_epoch
    dfi = _precompute_epochs(df_issues)
    created_map = dict(zip(dfi["key"], dfi["created_epoch"]))
    fallback = df_nd["key"].map(created_map)
    df_nd["last_transition"] = df_nd["last_transition"].fillna(df_nd["key"].map(created_map))
    df_nd["days_stale"] = ((now_ep - df_nd["last_transition"]) / 86400).round(1)
    return df_nd


def calc_time_to_assign(df_issues, df_changelog):
    """Time from creation to first assignee change (days)."""
    ac = df_changelog[df_changelog["field"].isin(["assignee", "Assignee"])]
    if len(ac) == 0:
        return pd.DataFrame()
    first_a = ac.groupby("issue_key")["created_epoch"].min()
    dfi = df_issues.copy()
    dfi["created_ts"] = pd.to_datetime(dfi["created"], errors="coerce")
    dfi["created_epoch"] = dfi["created_ts"].apply(
        lambda x: x.timestamp() if pd.notna(x) else None)
    dfi["first_assign_epoch"] = dfi["key"].map(first_a)
    dfi["days_to_assign"] = ((dfi["first_assign_epoch"] - dfi["created_epoch"]) / 86400).round(1)
    return dfi[dfi["days_to_assign"].notna() & (dfi["days_to_assign"] >= 0)]


def calc_cycle_time_trend(dff):
    """Monthly P50/P90 cycle time for resolved issues."""
    resolved = dff[dff["resolution_date"].notna()].copy()
    if len(resolved) == 0:
        return pd.DataFrame()
    resolved["lifetime"] = (resolved["resolution_date"] - resolved["created"]).dt.total_seconds() / 86400
    resolved = resolved[(resolved["lifetime"] >= 0) & (resolved["lifetime"] < 2000)]
    if len(resolved) == 0:
        return pd.DataFrame()
    resolved["ym"] = resolved["resolution_date"].dt.to_period("M").astype(str)
    monthly = resolved.groupby("ym").agg(
        p50=("lifetime", lambda x: safe_pct(x, 50)),
        p90=("lifetime", lambda x: safe_pct(x, 90)),
        mean=("lifetime", "mean"),
        count=("key", "count"),
    ).reset_index()
    monthly = monthly[monthly["count"] >= 3].sort_values("ym")
    monthly["p50_ma"] = monthly["p50"].rolling(3, min_periods=1).mean()
    monthly["p90_ma"] = monthly["p90"].rolling(3, min_periods=1).mean()
    return monthly


def calc_on_time_delivery(dff):
    """% of resolved issues closed before due_date."""
    resolved = dff[dff["resolution_date"].notna()].copy()
    has_due = resolved[resolved["due_date"].notna()].copy()
    if len(has_due) == 0:
        return pd.DataFrame()
    has_due["due_date"] = pd.to_datetime(has_due["due_date"], errors="coerce")
    has_due = has_due.dropna(subset=["due_date"])
    if len(has_due) == 0:
        return pd.DataFrame()
    has_due["on_time"] = has_due["resolution_date"] <= has_due["due_date"]
    has_due["ym"] = has_due["resolution_date"].dt.to_period("M").astype(str)
    monthly = has_due.groupby("ym").agg(
        total=("key", "count"),
        on_time=("on_time", "sum"),
    ).reset_index()
    monthly["pct"] = (monthly["on_time"] / monthly["total"] * 100).round(1)
    monthly = monthly[monthly["total"] >= 3].sort_values("ym")
    return monthly


def calc_predictability(dff):
    """Coefficient of variation of monthly resolved throughput."""
    resolved = dff[dff["resolution_date"].notna()].copy()
    if len(resolved) == 0:
        return None
    resolved["ym"] = resolved["resolution_date"].dt.to_period("M").astype(str)
    monthly = resolved.groupby("ym").size()
    if len(monthly) < 3:
        return None
    mean_tp = monthly.mean()
    std_tp = monthly.std()
    cv = std_tp / mean_tp if mean_tp > 0 else None
    return {"mean": mean_tp, "std": std_tp, "cv": cv, "monthly": monthly.to_dict()}


def calc_rework_trend(dft_f, smap):
    """Monthly rework rate (backward transitions)."""
    if len(dft_f) == 0:
        return pd.DataFrame()
    df = dft_f.copy()
    df["dt"] = pd.to_datetime(df["transition_epoch"], unit="s", errors="coerce")
    df["ym"] = df["dt"].dt.to_period("M").astype(str)

    rework_data = []
    for key, group in df.groupby("issue_key"):
        group = group.sort_values("transition_epoch")
        prev_cat = categorize(group.iloc[0]["from_status"], smap)
        for _, r in group.iterrows():
            curr_cat = categorize(r["to_status"], smap)
            if CAT_ORDER.get(curr_cat, 0) < CAT_ORDER.get(prev_cat, 0):
                rework_data.append({"key": key, "ym": r["ym"]})
                break
            prev_cat = curr_cat

    if len(rework_data) == 0:
        return pd.DataFrame()

    rework_df = pd.DataFrame(rework_data)
    rework_per_month = rework_df.groupby("ym").size()
    total_per_month = df.groupby("ym")["issue_key"].nunique()

    out = pd.DataFrame({"total": total_per_month}).reset_index()
    out["rework"] = out["ym"].map(rework_per_month).fillna(0).astype(int)
    out["pct"] = (out["rework"] / out["total"] * 100).round(1)
    out = out[out["total"] >= 3].sort_values("ym")
    out["pct_ma"] = out["pct"].rolling(3, min_periods=1).mean()
    return out


def calc_queue_vs_process(dff, bl_df, ip_df):
    """Monthly queue time (To Do) vs process time (In Progress)."""
    resolved = dff[dff["resolution_date"].notna()].copy()
    if len(resolved) == 0:
        return pd.DataFrame()
    resolved["ym"] = resolved["resolution_date"].dt.to_period("M").astype(str)
    merged = resolved.merge(bl_df, on="key", how="left").merge(ip_df, on="key", how="left")
    monthly = merged.groupby("ym").agg(
        queue=("backlog_days", "median"),
        process=("in_progress_days", "median"),
        count=("key", "count"),
    ).reset_index()
    monthly = monthly[monthly["count"] >= 3].sort_values("ym")
    monthly["queue_ma"] = monthly["queue"].rolling(3, min_periods=1).mean()
    monthly["process_ma"] = monthly["process"].rolling(3, min_periods=1).mean()
    return monthly


def calc_estimation_trend(dff):
    """Monthly estimation accuracy ratio (actual / estimated)."""
    est = dff[(dff["original_estimate"].notna()) & (dff["time_spent"].notna()) &
               (dff["original_estimate"] > 0) & (dff["time_spent"] > 0)].copy()
    if len(est) == 0:
        return pd.DataFrame()
    est["ratio"] = est["time_spent"] / est["original_estimate"]
    est["resolved"] = pd.to_datetime(est["resolution_date"], errors="coerce")
    est = est[est["resolved"].notna()]
    if len(est) == 0:
        return pd.DataFrame()
    est["ym"] = est["resolved"].dt.to_period("M").astype(str)
    monthly = est.groupby("ym").agg(
        mean_ratio=("ratio", "mean"),
        median_ratio=("ratio", "median"),
        count=("key", "count"),
    ).reset_index()
    monthly = monthly[monthly["count"] >= 3].sort_values("ym")
    monthly["mean_ma"] = monthly["mean_ratio"].rolling(3, min_periods=1).mean()
    return monthly


def calc_cycle_time_per_person(dff):
    """Cycle time (created -> resolved) per assignee."""
    resolved = dff[dff["resolution_date"].notna() & dff["assignee_name"].notna()].copy()
    if len(resolved) == 0:
        return pd.DataFrame()
    resolved["lifetime"] = (resolved["resolution_date"] - resolved["created"]).dt.total_seconds() / 86400
    resolved = resolved[(resolved["lifetime"] >= 0) & (resolved["lifetime"] < 2000)]
    if len(resolved) == 0:
        return pd.DataFrame()
    per_person = resolved.groupby("assignee_name").agg(
        median_cycle=("lifetime", "median"),
        p90_cycle=("lifetime", lambda x: safe_pct(x, 90)),
        count=("key", "count"),
    ).reset_index()
    per_person = per_person[per_person["count"] >= 5]
    return per_person.sort_values("median_cycle", ascending=True)


def calc_hours_vs_tasks(dff, dfw):
    """Logged hours vs completed tasks per person."""
    resolved = dff[dff["resolution_date"].notna() & dff["assignee_name"].notna()].copy()
    closed_counts = resolved.groupby("assignee_name").size().reset_index(name="tasks")

    if len(dfw) > 0:
        wl = dfw[dfw["issue_key"].isin(dff["key"])].copy()
        wl_hours = wl.groupby("author_name")["time_spent_seconds"].sum() / 3600
        wl_hours = wl_hours.round(1).reset_index(name="hours")
        merged = closed_counts.merge(wl_hours, left_on="assignee_name", right_on="author_name", how="left")
        merged["hours"] = merged["hours"].fillna(0)
    else:
        merged = closed_counts
        merged["hours"] = 0
    return merged


def calc_rework_per_person(dff, dft_f, smap):
    """Rework rate per assignee."""
    if len(dft_f) == 0:
        return pd.DataFrame()

    rework_issues = set()
    for key, group in dft_f.groupby("issue_key"):
        group = group.sort_values("transition_epoch")
        prev_cat = categorize(group.iloc[0]["from_status"], smap)
        for _, r in group.iterrows():
            curr_cat = categorize(r["to_status"], smap)
            if CAT_ORDER.get(curr_cat, 0) < CAT_ORDER.get(prev_cat, 0):
                rework_issues.add(key)
                break
            prev_cat = curr_cat

    assigned = dff[dff["assignee_name"].notna()].copy()
    assigned["has_rework"] = assigned["key"].isin(rework_issues)
    per_person = assigned.groupby("assignee_name").agg(
        total=("key", "count"),
        rework=("has_rework", "sum"),
    ).reset_index()
    per_person["pct"] = (per_person["rework"] / per_person["total"] * 100).round(1)
    per_person = per_person[per_person["total"] >= 5]
    return per_person.sort_values("pct", ascending=True)


def calc_estimation_per_person(dff):
    """Estimation accuracy per assignee."""
    est = dff[(dff["original_estimate"].notna()) & (dff["time_spent"].notna()) &
               (dff["original_estimate"] > 0) & (dff["time_spent"] > 0) &
               (dff["assignee_name"].notna())].copy()
    if len(est) == 0:
        return pd.DataFrame()
    est["ratio"] = est["time_spent"] / est["original_estimate"]
    per_person = est.groupby("assignee_name").agg(
        mean_ratio=("ratio", "mean"),
        median_ratio=("ratio", "median"),
        count=("key", "count"),
    ).reset_index()
    per_person = per_person[per_person["count"] >= 3]
    return per_person.sort_values("mean_ratio", ascending=True)


def calc_stale_per_person(dff, dft_f):
    """Stale WIP count per assignee."""
    stale = calc_stale(dff, dft_f)
    if len(stale) == 0:
        return pd.DataFrame()
    stale = stale[stale["assignee_name"].notna()]
    per_person = stale.groupby("assignee_name").agg(
        stale_count=("key", "count"),
        avg_days=("days_stale", "mean"),
        max_days=("days_stale", "max"),
    ).reset_index()
    return per_person.sort_values("stale_count", ascending=True)


def calc_concurrent_wip_per_person(dff):
    """Current WIP (In Progress) count per assignee."""
    in_prog = dff[dff["status_category"] == "In Progress"].copy()
    if len(in_prog) == 0:
        return pd.DataFrame()
    in_prog = in_prog[in_prog["assignee_name"].notna()]
    per_person = in_prog.groupby("assignee_name").size().reset_index(name="wip_count")
    return per_person.sort_values("wip_count", ascending=True)


def reshape_yoy(monthly_df, ym_col="ym", val_col="median_days", min_year=2020):
    """Reshape monthly data to year-over-year format (month 1-12 as rows, year as columns)."""
    if len(monthly_df) == 0:
        return pd.DataFrame()
    df = monthly_df.copy()
    parts = df[ym_col].str.split("-", expand=True)
    df["year"] = parts[0].astype(int)
    df["month"] = parts[1].astype(int)
    df = df[df["year"] >= min_year]
    pivot = df.pivot_table(index="month", columns="year", values=val_col, aggfunc="first")
    return pivot.reset_index()


def calc_first_time_right(dff, dft_f, smap):
    """First-Time-Right rate: % of resolved issues that never went backward."""
    resolved_keys = set(dff[dff["resolution_date"].notna()]["key"])
    if len(resolved_keys) == 0:
        return 0, 0, pd.DataFrame()
    rework_keys = set()
    monthly = {}
    for key, group in dft_f[dft_f["issue_key"].isin(resolved_keys)].groupby("issue_key"):
        group = group.sort_values("transition_epoch")
        prev_cat = categorize(group.iloc[0]["from_status"], smap)
        has_backward = False
        for _, r in group.iterrows():
            curr_cat = categorize(r["to_status"], smap)
            if CAT_ORDER.get(curr_cat, 0) < CAT_ORDER.get(prev_cat, 0):
                has_backward = True
                break
            prev_cat = curr_cat
        if has_backward:
            rework_keys.add(key)
    ftr_keys = resolved_keys - rework_keys
    total = len(resolved_keys)
    ftr = len(ftr_keys)
    pct = ftr / total * 100 if total > 0 else 0

    # Monthly FTR trend
    resolved_df = dff[dff["resolution_date"].notna()].copy()
    resolved_df["ym"] = resolved_df["resolution_date"].dt.to_period("M").astype(str)
    resolved_df["ftr"] = ~resolved_df["key"].isin(rework_keys)
    monthly_trend = resolved_df.groupby("ym").agg(
        total=("key", "count"),
        ftr_count=("ftr", "sum"),
    ).reset_index()
    monthly_trend["pct"] = (monthly_trend["ftr_count"] / monthly_trend["total"] * 100).round(1)
    monthly_trend = monthly_trend[monthly_trend["total"] >= 3].sort_values("ym")
    monthly_trend["pct_ma"] = monthly_trend["pct"].rolling(3, min_periods=1).mean()
    return ftr, total, monthly_trend


def calc_review_reject_rate(dft_f):
    """Count tasks that went from In Review back to In Progress (rejected review).

    Monthly trend shows the actual monthly reject RATE (rejections / tasks in
    review that month), not a distribution of all-time rejections.
    """
    REVIEW_STATUSES = ("In Review", "In review (Design)")
    EXIT_STATUSES = ("In Review", "In review (Design)", "Done", "Closed", "Resolved")
    reject_keys = set()
    total_review_keys = set()
    monthly_rej = {}   # ym -> count of rejections
    monthly_rev = {}   # ym -> set of keys in review that month
    for key, group in dft_f.groupby("issue_key"):
        group = group.sort_values("transition_epoch")
        prev_status = str(group.iloc[0]["from_status"])
        rejected_this = False
        for _, r in group.iterrows():
            curr_status = str(r["to_status"])
            if prev_status in REVIEW_STATUSES:
                total_review_keys.add(key)
                dt = pd.to_datetime(r["transition_epoch"], unit="s", errors="coerce")
                if pd.notna(dt):
                    ym = dt.strftime("%Y-%m")
                    monthly_rev.setdefault(ym, set()).add(key)
            if prev_status in REVIEW_STATUSES and curr_status not in EXIT_STATUSES:
                if not rejected_this:
                    reject_keys.add(key)
                    dt = pd.to_datetime(r["transition_epoch"], unit="s", errors="coerce")
                    if pd.notna(dt):
                        ym = dt.strftime("%Y-%m")
                        monthly_rej.setdefault(ym, 0)
                        monthly_rej[ym] += 1
                rejected_this = True
            prev_status = curr_status

    total = len(total_review_keys)
    rejected = len(reject_keys)
    pct = rejected / total * 100 if total > 0 else 0

    all_yms = sorted(set(list(monthly_rej.keys()) + list(monthly_rev.keys())))
    if len(all_yms) > 0:
        rows = []
        for ym in all_yms:
            rej = monthly_rej.get(ym, 0)
            in_rev = len(monthly_rev.get(ym, set()))
            rate = rej / in_rev * 100 if in_rev > 0 else 0
            rows.append({"ym": ym, "rejected": rej, "in_review": in_rev, "pct": round(rate, 1)})
        monthly_trend = pd.DataFrame(rows).sort_values("ym")
        monthly_trend = monthly_trend[monthly_trend["in_review"] >= 3]
        monthly_trend["pct_ma"] = monthly_trend["pct"].rolling(3, min_periods=1).mean()
    else:
        monthly_trend = pd.DataFrame()
    return rejected, total, pct, monthly_trend


def calc_time_in_each_status(df_issues, df_trans):
    """Median time in each individual status (not category)."""
    all_statuses = set(df_trans["from_status"].dropna().unique()) | set(df_trans["to_status"].dropna().unique())
    results = []
    for status in sorted(all_statuses):
        res = calc_time_in_status(df_issues, df_trans, [status])
        if len(res) > 0 and res["status_days"].sum() > 0:
            results.append({
                "status": status,
                "median_days": res["status_days"].median(),
                "mean_days": res["status_days"].mean(),
                "count": len(res),
            })
    return pd.DataFrame(results).sort_values("median_days", ascending=True)


def calc_aging_wip(dff, dft_f):
    """Age distribution of current In-Progress tasks (days since last transition)."""
    now_ep = datetime.now().timestamp()
    in_prog_keys = dff[dff["status_category"] == "In Progress"]["key"].tolist()
    if len(in_prog_keys) == 0:
        return pd.DataFrame()
    last_t = dft_f[dft_f["issue_key"].isin(in_prog_keys)].groupby("issue_key")["transition_epoch"].max()
    result = dff[dff["key"].isin(in_prog_keys)].copy()
    result["last_transition"] = result["key"].map(last_t)
    result["age_days"] = ((now_ep - result["last_transition"]) / 86400).round(1)
    return result.dropna(subset=["age_days"])


def calc_gini(values):
    """Calculate Gini coefficient (0=equal, 1=unequal).

    Includes zeros — a person with 0 tasks affects inequality.
    Filtering zeros (old code) reduced n and hid inequality.
    """
    vals = sorted([v for v in values if v >= 0])
    n = len(vals)
    if n == 0:
        return 0
    cumsum = sum(vals)
    if cumsum == 0:
        return 0
    idx = sum((i + 1) * v for i, v in enumerate(vals))
    return (2 * idx) / (n * cumsum) - (n + 1) / n


def calc_handoff_count(dff, dfc):
    """Count assignee changes per issue (handoffs)."""
    ac = dfc[dfc["field"].isin(["assignee", "Assignee"])]
    if len(ac) == 0:
        return pd.DataFrame()
    ac_f = ac[ac["issue_key"].isin(dff["key"])]
    handoffs = ac_f.groupby("issue_key").size().reset_index(name="handoffs")
    handoffs = handoffs.merge(dff[["key", "project_key", "summary", "status", "assignee_name"]],
                              left_on="issue_key", right_on="key", how="left")
    return handoffs.sort_values("handoffs", ascending=False)


def calc_priority_vs_cycle_time(dff):
    """Cycle time by priority level."""
    resolved = dff[dff["resolution_date"].notna() & dff["priority"].notna()].copy()
    if len(resolved) == 0:
        return pd.DataFrame()
    resolved["lifetime"] = (resolved["resolution_date"] - resolved["created"]).dt.total_seconds() / 86400
    resolved = resolved[(resolved["lifetime"] >= 0) & (resolved["lifetime"] < 2000)]
    if len(resolved) == 0:
        return pd.DataFrame()
    per_priority = resolved.groupby("priority").agg(
        median_cycle=("lifetime", "median"),
        p90_cycle=("lifetime", lambda x: safe_pct(x, 90)),
        mean_cycle=("lifetime", "mean"),
        count=("key", "count"),
    ).reset_index()
    return per_priority.sort_values("median_cycle", ascending=True)


def calc_project_comparison(dff):
    """Cycle time and throughput by project."""
    resolved = dff[dff["resolution_date"].notna()].copy()
    if len(resolved) == 0:
        return pd.DataFrame()
    resolved["lifetime"] = (resolved["resolution_date"] - resolved["created"]).dt.total_seconds() / 86400
    resolved = resolved[(resolved["lifetime"] >= 0) & (resolved["lifetime"] < 2000)]
    per_project = resolved.groupby("project_key").agg(
        median_cycle=("lifetime", "median"),
        p90_cycle=("lifetime", lambda x: safe_pct(x, 90)),
        resolved_count=("key", "count"),
    ).reset_index()
    total_counts = dff.groupby("project_key")["key"].count().reset_index(name="total_count")
    per_project = per_project.merge(total_counts, on="project_key", how="left")
    return per_project.sort_values("median_cycle", ascending=True)


def calc_component_cycle_time(dff):
    """Median cycle time by product component."""
    comp = dff[dff["components"].notna() & (dff["components"] != "") & dff["resolution_date"].notna()].copy()
    if len(comp) == 0:
        return pd.DataFrame()
    comp["lifetime"] = (comp["resolution_date"] - comp["created"]).dt.total_seconds() / 86400
    comp = comp[(comp["lifetime"] >= 0) & (comp["lifetime"] < 2000)]
    if len(comp) == 0:
        return pd.DataFrame()
    comp["comp_list"] = comp["components"].str.split("[,;]")
    comp_ex = comp.explode("comp_list")
    comp_ex["comp_list"] = comp_ex["comp_list"].str.strip()
    comp_ex = comp_ex[comp_ex["comp_list"] != ""]
    if len(comp_ex) == 0:
        return pd.DataFrame()
    per_comp = comp_ex.groupby("comp_list").agg(
        median_cycle=("lifetime", "median"),
        mean_cycle=("lifetime", "mean"),
        count=("key", "count"),
    ).reset_index()
    per_comp = per_comp[per_comp["count"] >= 5]
    return per_comp.sort_values("median_cycle", ascending=True)


def calc_qoq_summary(dff, dft_f, smap):
    """Quarter-over-quarter comparison of key metrics."""
    resolved = dff[dff["resolution_date"].notna()].copy()
    if len(resolved) == 0:
        return pd.DataFrame()
    resolved["lifetime"] = (resolved["resolution_date"] - resolved["created"]).dt.total_seconds() / 86400
    resolved = resolved[(resolved["lifetime"] >= 0) & (resolved["lifetime"] < 2000)]
    resolved["quarter"] = resolved["resolution_date"].dt.to_period("Q").astype(str)

    # Rework per quarter
    rework_keys = set()
    for key, group in dft_f.groupby("issue_key"):
        group = group.sort_values("transition_epoch")
        prev_cat = categorize(group.iloc[0]["from_status"], smap)
        for _, r in group.iterrows():
            curr_cat = categorize(r["to_status"], smap)
            if CAT_ORDER.get(curr_cat, 0) < CAT_ORDER.get(prev_cat, 0):
                rework_keys.add(key)
                break
            prev_cat = curr_cat
    resolved["has_rework"] = resolved["key"].isin(rework_keys)

    quarterly = resolved.groupby("quarter").agg(
        resolved_count=("key", "count"),
        median_cycle=("lifetime", "median"),
        mean_cycle=("lifetime", "mean"),
        rework_count=("has_rework", "sum"),
    ).reset_index()
    quarterly["rework_pct"] = (quarterly["rework_count"] / quarterly["resolved_count"] * 100).round(1)
    quarterly = quarterly.sort_values("quarter")
    # Calculate deltas
    quarterly["resolved_delta"] = quarterly["resolved_count"].pct_change() * 100
    quarterly["cycle_delta"] = quarterly["median_cycle"].diff()
    quarterly["rework_delta"] = quarterly["rework_pct"].diff()
    return quarterly


# ============================================================
#  MAIN
# ============================================================

def main():
    st.title("🎨 Jira Design Insights")
    st.markdown("Статистика по design-задачам во всех проектах AdGuard (2018–2026)")

    df = load_issues()
    dft = load_transitions()
    dfw = load_worklogs()
    dfc = load_changelog()

    # Parse dates
    for col in ["created", "updated", "resolution_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["created_year"] = df["created"].dt.year
    df["created_month"] = df["created"].dt.to_period("M").astype(str)

    smap = get_status_map(df)

    # ---- Sidebar filters ----
    st.sidebar.header("Фильтры")

    # Date range — max_value is today, not last data point, so user can select current date
    min_date = df["created"].min().date() if df["created"].notna().any() else datetime(2018, 1, 1).date()
    max_date = datetime.now().date()
    date_range = st.sidebar.date_input("Дата создания", [min_date, max_date],
                                         min_value=min_date, max_value=max_date)

    # Multi-select filters
    projects = sorted(df["project_key"].dropna().unique().tolist())
    sel_projects = st.sidebar.multiselect("Проекты", projects)

    assignees = sorted(df["assignee_name"].dropna().unique().tolist())
    sel_assignees = st.sidebar.multiselect("Исполнители", assignees)

    statuses = sorted(df["status"].dropna().unique().tolist())
    sel_statuses = st.sidebar.multiselect("Статусы", statuses)

    # Apply filters
    mask = df["created"].notna()
    if len(date_range) == 2:
        mask &= df["created"] >= pd.Timestamp(date_range[0])
        mask &= df["created"] <= pd.Timestamp(date_range[1]) + pd.Timedelta(days=1)
    if sel_projects:
        mask &= df["project_key"].isin(sel_projects)
    if sel_assignees:
        mask &= df["assignee_name"].isin(sel_assignees)
    if sel_statuses:
        mask &= df["status"].isin(sel_statuses)

    dff = df[mask].copy()
    dft_f = dft[dft["issue_key"].isin(dff["key"])] if "key" in dff.columns else dft

    # Precompute expensive calculations once for all tabs
    ip_df = calc_time_in_progress(dff, dft_f)
    bl_df = calc_time_in_backlog(dff, dft_f)

    # ---- Tabs ----
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Overview", "🔄 Cycle Time & Flow", "👥 People", "🔬 Deep Dives", "🔍 Data Explorer"
    ])

    # ===================== TAB 1: OVERVIEW =====================
    with tab1:
        st.markdown("## 📊 Общая статистика")
        st.caption("Сводные метрики по задачам: всего, закрыто, в работе, в бэклоге, без исполнителя и процент с логированным временем.")

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        total = len(dff)
        done = (dff["status_category"] == "Done").sum()
        in_prog = (dff["status_category"] == "In Progress").sum()
        todo = (dff["status_category"] == "To Do").sum()
        no_assignee = dff["assignee_name"].isna().sum()

        # Worklog coverage
        issues_with_wl = dff["key"].isin(dfw["issue_key"].unique()).sum() if len(dfw) > 0 else 0
        wl_pct = (issues_with_wl / total * 100) if total > 0 else 0

        col1.metric("Всего задач", total)
        col2.metric("Закрыто", int(done))
        col3.metric("В работе", int(in_prog))
        col4.metric("В бэклоге", int(todo))
        col5.metric("Без исполнителя", int(no_assignee))
        col6.metric("Логируется время", f"{wl_pct:.0f}%")

        st.markdown("---")

        # Throughput with rolling MA
        st.markdown("### 📈 Throughput: создание vs закрытие (3-month MA)")
        st.caption("Сколько задач создавалось и закрывалось каждый месяц. Скользящее среднее за 3 месяца сглаживает выбросы и показывает тренд.")

        monthly = dff.groupby("created_month").agg(created_count=("key", "count")).reset_index()
        resolved_df = dff[dff["resolution_date"].notna()].copy()
        resolved_df["resolved_month"] = resolved_df["resolution_date"].dt.to_period("M").astype(str)
        resolved_monthly = resolved_df.groupby("resolved_month").size().reset_index(name="resolved_count")
        resolved_monthly.rename(columns={"resolved_month": "created_month"}, inplace=True)
        monthly = monthly.merge(resolved_monthly, on="created_month", how="outer").fillna(0)
        monthly = monthly.sort_values("created_month")
        monthly = monthly[monthly["created_month"] >= "2020-01"]
        monthly["created_ma"] = monthly["created_count"].rolling(3, min_periods=1).mean()
        monthly["resolved_ma"] = monthly["resolved_count"].rolling(3, min_periods=1).mean()

        fig = go.Figure()
        fig.add_trace(go.Bar(x=monthly["created_month"], y=monthly["created_count"],
                            name="Создано", marker_color="#636EFA", opacity=0.5))
        fig.add_trace(go.Bar(x=monthly["created_month"], y=monthly["resolved_count"],
                            name="Закрыто", marker_color="#2CA02C", opacity=0.5))
        fig.add_trace(go.Scatter(x=monthly["created_month"], y=monthly["created_ma"],
                                name="Создано (MA3)", line=dict(color="#636EFA", width=2)))
        fig.add_trace(go.Scatter(x=monthly["created_month"], y=monthly["resolved_ma"],
                                name="Закрыто (MA3)", line=dict(color="#2CA02C", width=2)))
        fig.update_layout(barmode="group", height=400,
                          xaxis_title="Месяц", yaxis_title="Количество")
        st.plotly_chart(fig, use_container_width=True)

        # Weighted throughput: effort and duration
        st.markdown("### ⚖️ Сложность задач: логированное время и длительность")
        st.caption("Дополнительный разрез к throughput выше. Левый график — сколько часов залогировано в месяц (объём работы). Правый — среднее время задач в активной работе (In Progress). Если количество задач стабильно, но часы растут — задачи крупнее. Если дни в работе растут — процесс замедляется.")

        col_eff1, col_eff2 = st.columns(2)

        with col_eff1:
            st.markdown("#### 🕐 Залогированные часы по месяцам")
            st.caption("Данные логирования доступны с мая 2023 — раньше учёт времени не вёлся.")
            if len(dfw) > 0:
                wl_eff = dfw[dfw["issue_key"].isin(dff["key"])].copy()
                wl_eff["started"] = pd.to_datetime(wl_eff["started"], errors="coerce")
                wl_eff = wl_eff.dropna(subset=["started"])
                wl_eff["ym"] = wl_eff["started"].dt.to_period("M").astype(str)
                eff_monthly = wl_eff.groupby("ym").agg(
                    hours=("time_spent_seconds", lambda x: x.sum() / 3600),
                    entries=("issue_key", "count"),
                ).reset_index()
                eff_monthly = eff_monthly[eff_monthly["ym"] >= "2020-01"].sort_values("ym")
                eff_monthly["hours_ma"] = eff_monthly["hours"].rolling(3, min_periods=1).mean()

                fig = go.Figure()
                fig.add_trace(go.Bar(x=eff_monthly["ym"], y=eff_monthly["hours"],
                                     name="Часы", marker_color="#FF9F43", opacity=0.5))
                fig.add_trace(go.Scatter(x=eff_monthly["ym"], y=eff_monthly["hours_ma"],
                                        name="MA3", line=dict(color="#E67E22", width=2)))
                fig.update_layout(height=350, xaxis_title="Месяц", yaxis_title="Залогировано часов",
                                  legend=dict(orientation="h", y=1.12))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет данных по логированию времени.")

        with col_eff2:
            st.markdown("#### 📏 Среднее время в работе (In Progress)")
            ip_valid = ip_df.dropna(subset=["in_progress_days"])
            # Cap extreme outliers at P95 for meaningful chart
            if len(ip_valid) > 10:
                p95_cap = np.percentile(ip_valid[ip_valid["in_progress_days"] > 0]["in_progress_days"], 95)
                ip_valid = ip_valid[ip_valid["in_progress_days"] <= p95_cap]
            ip_valid = ip_valid[ip_valid["in_progress_days"] > 0]
            if len(ip_valid) > 0:
                resolved_with_ip = dff[dff["resolution_date"].notna()].merge(
                    ip_valid, on="key", how="inner")
                if len(resolved_with_ip) > 0:
                    resolved_with_ip["resolved_month"] = (
                        resolved_with_ip["resolution_date"].dt.to_period("M").astype(str))
                    ip_monthly = resolved_with_ip.groupby("resolved_month").agg(
                        avg_days=("in_progress_days", "mean"),
                        median_days=("in_progress_days", "median"),
                        count=("key", "count"),
                    ).reset_index()
                    # Filter months with < 3 tasks (outlier-prone)
                    ip_monthly = ip_monthly[(ip_monthly["resolved_month"] >= "2020-01") & (ip_monthly["count"] >= 3)].sort_values("resolved_month")
                    ip_monthly["avg_ma"] = ip_monthly["avg_days"].rolling(3, min_periods=1).mean()

                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=ip_monthly["resolved_month"], y=ip_monthly["avg_days"],
                                         name="Среднее (дни)", marker_color="#74B9FF", opacity=0.5))
                    fig.add_trace(go.Scatter(x=ip_monthly["resolved_month"], y=ip_monthly["avg_ma"],
                                            name="MA3", line=dict(color="#0984E3", width=2)))
                    fig.add_trace(go.Scatter(x=ip_monthly["resolved_month"], y=ip_monthly["median_days"],
                                            name="Медиана", line=dict(color="#6C5CE7", width=1, dash="dot")))
                    fig.update_layout(height=350, xaxis_title="Месяц закрытия",
                                      yaxis_title="Дни в In Progress",
                                      legend=dict(orientation="h", y=1.12))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Нет закрытых задач с временем в работе.")
            else:
                st.info("Нет данных по времени в активной работе.")

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("### 📋 По статусам")
            st.caption("Распределение задач по текущим Jira-статусам (Open, In Progress, Done и т.д.).")
            sc = dff.groupby("status").size().reset_index(name="count").sort_values("count", ascending=True)
            fig = px.bar(sc, x="count", y="status", orientation="h",
                        labels={"count": "Кол-во", "status": ""}, color="count",
                        color_continuous_scale="Viridis")
            fig.update_layout(height=450, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            st.markdown("### 📁 По проектам")
            st.caption("Количество задач в разрезе проектов AdGuard (AGM, ADG, AG, EML и т.д.).")
            pc = dff.groupby(["project_key", "project_name"]).size().reset_index(name="count")
            pc = pc.sort_values("count", ascending=False)
            fig = px.bar(pc, x="project_key", y="count",
                        labels={"project_key": "Проект", "count": "Кол-во"},
                        color="count", color_continuous_scale="Blues")
            fig.update_layout(height=450, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        # Yearly throughput
        st.markdown("### 📅 По годам")
        st.caption("Годовая агрегация: сколько задач создано и сколько закрыто в каждом году.")
        yearly = dff.groupby("created_year").agg(
            created=("key", "count"),
            resolved=("resolution", lambda x: x.notna().sum()),
        ).reset_index()
        fig = go.Figure()
        fig.add_trace(go.Bar(x=yearly["created_year"], y=yearly["created"],
                             name="Создано", marker_color="#636EFA"))
        fig.add_trace(go.Bar(x=yearly["created_year"], y=yearly["resolved"],
                             name="Закрыто", marker_color="#2CA02C"))
        fig.update_layout(barmode="group", height=350,
                          xaxis_title="Год", yaxis_title="Количество")
        st.plotly_chart(fig, use_container_width=True)

    # ===================== TAB 2: CYCLE TIME & FLOW =====================
    with tab2:
        st.markdown("## 🔄 Cycle Time & Flow")
        st.caption("Анализ времени прохождения задач через статусы: процентили, узкие места (bottlenecks), накопительная диаграмма и воронка переходов.")

        # Percentiles table
        st.markdown("### 📊 Percentiles времени в статусе (дни)")
        st.caption("Для каждого статуса — сколько дней задача в нём находилась: среднее, медиана (P50), P75, P90, P95. Чем выше P90/P95, тем больше задач «залипает» в этом статусе.")

        if len(dft_f) > 0:
            tr_sorted = dft_f.sort_values(["issue_key", "transition_epoch"])
            tr_sorted["next_epoch"] = tr_sorted.groupby("issue_key")["transition_epoch"].shift(-1)
            tr_sorted["hours_in"] = (tr_sorted["next_epoch"] - tr_sorted["transition_epoch"]) / 3600
            tr_valid = tr_sorted[(tr_sorted["hours_in"] > 0) & (tr_sorted["hours_in"] < 876000)]

            if len(tr_valid) > 0:
                pct_data = []
                for status, grp in tr_valid.groupby("to_status"):
                    days = grp["hours_in"] / 24
                    pct_data.append({
                        "Статус": status,
                        "Переходов": len(grp),
                        "Среднее (дни)": round(days.mean(), 1),
                        "P50": round(safe_pct(days, 50), 1),
                        "P75": round(safe_pct(days, 75), 1),
                        "P90": round(safe_pct(days, 90), 1),
                        "P95": round(safe_pct(days, 95), 1),
                        "Макс (дни)": round(days.max(), 0),
                    })
                pct_df = pd.DataFrame(pct_data).sort_values("Среднее (дни)", ascending=False)
                st.dataframe(pct_df, use_container_width=True, hide_index=True)

                # Bottleneck chart — exclude terminal Done-statuses (they're not bottlenecks)
                st.markdown("### 🚧 Bottleneck: среднее время в статусе")
                st.caption("Горизонтальная диаграмма показывает, в каких статусах задачи проводят больше всего времени в среднем. Терминальные статусы (Closed, Done, Cancelled) исключены — они не узкие места, а финальные точки.")
                bn_all = pct_df.copy()
                # Filter out Done-category statuses from bottleneck
                bn_statuses = bn_all[bn_all["Статус"].apply(lambda s: categorize(s, smap) != "Done")]
                if len(bn_statuses) == 0:
                    bn_statuses = bn_all
                bn = bn_statuses.sort_values("Среднее (дни)", ascending=True)
                fig = px.bar(bn, x="Среднее (дни)", y="Статус", orientation="h",
                             color="Среднее (дни)", color_continuous_scale="Turbo",
                             labels={"Статус": ""})
                fig.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        # CFD
        st.markdown("### 📈 Cumulative Flow Diagram")
        st.caption("Накопительная диаграмма потока: сколько задач одновременно находилось в каждой категории (To Do, In Progress, Done) на конец каждого месяца. Растущий разрыв между In Progress и Done сигнализирует о瓶颈е.")
        with st.spinner("Строим CFD..."):
            cfd_df = build_cfd(dff, dft_f)
        cfd_show = cfd_df[cfd_df["month"] >= "2020-01"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=cfd_show["month"], y=cfd_show["Done"], stackgroup="1",
                                 name="Done", line=dict(width=0), fillcolor="rgba(44,160,44,0.6)"))
        fig.add_trace(go.Scatter(x=cfd_show["month"], y=cfd_show["In Progress"], stackgroup="1",
                                 name="In Progress", line=dict(width=0), fillcolor="rgba(255,165,0,0.6)"))
        fig.add_trace(go.Scatter(x=cfd_show["month"], y=cfd_show["To Do"], stackgroup="1",
                                 name="To Do", line=dict(width=0), fillcolor="rgba(99,110,250,0.6)"))
        fig.update_layout(height=450, xaxis_title="Месяц", yaxis_title="Количество задач",
                          legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig, use_container_width=True)

        # Sankey status flow — two views: by category (clean funnel) and by individual status
        st.markdown("### 🌊 Status Flow (Sankey)")
        st.caption("Воронка движения задач между статусами. Первая диаграмма группирует по категориям (To Do → In Progress → Done) для наглядной воронки. Вторая показывает переходы между конкретными Jira-статуcами (переходы ≥ 15). Цвет узла = категория: синий = To Do, оранжевый = In Progress, зелёный = Done.")
        if len(dft_f) > 0:
            flow_raw = dft_f.copy()

            # --- Category-level Sankey (clean funnel) ---
            flow_cat = flow_raw.copy()
            flow_cat["from_cat"] = flow_cat["from_status"].apply(lambda s: categorize(s, smap))
            flow_cat["to_cat"] = flow_cat["to_status"].apply(lambda s: categorize(s, smap))
            flow_cat = flow_cat[flow_cat["from_cat"] != flow_cat["to_cat"]]
            cat_order_list = ["To Do", "In Progress", "Done"]
            cat_colors = {"To Do": "#636EFA", "In Progress": "#FFA500", "Done": "#2CA02C"}
            if len(flow_cat) > 0:
                cat_flow = flow_cat.groupby(["from_cat", "to_cat"]).size().reset_index(name="count")
                fig1 = go.Figure(data=[go.Sankey(
                    node=dict(
                        label=cat_order_list,
                        pad=40,
                        thickness=30,
                        color=[cat_colors[c] for c in cat_order_list],
                    ),
                    link=dict(
                        source=[cat_order_list.index(s) for s in cat_flow["from_cat"]],
                        target=[cat_order_list.index(s) for s in cat_flow["to_cat"]],
                        value=cat_flow["count"],
                        color="rgba(150,150,150,0.25)",
                    )
                )])
                fig1.update_layout(title="По категориям", height=350)
                st.plotly_chart(fig1, use_container_width=True)

            # --- Individual status Sankey (detailed) ---
            flow = flow_raw.groupby(["from_status", "to_status"]).size().reset_index(name="count")
            flow = flow[flow["count"] >= 15]
            if len(flow) > 0:
                all_s = sorted(set(flow["from_status"].tolist() + flow["to_status"].tolist()))
                s_idx = {s: i for i, s in enumerate(all_s)}
                node_colors = [cat_colors.get(categorize(s, smap), "#999") for s in all_s]
                fig2 = go.Figure(data=[go.Sankey(
                    node=dict(
                        label=all_s,
                        pad=25,
                        thickness=20,
                        color=node_colors,
                    ),
                    link=dict(
                        source=[s_idx[s] for s in flow["from_status"]],
                        target=[s_idx[s] for s in flow["to_status"]],
                        value=flow["count"],
                        color="rgba(150,150,150,0.2)",
                    )
                )])
                fig2.update_layout(title="По статусам (переходы ≥ 15)", height=550)
                st.plotly_chart(fig2, use_container_width=True)

        # Lifetime distribution
        st.markdown("### ⏳ Время жизни закрытых задач (создание → закрытие)")
        st.caption("Сколько дней проходит от создания задачи до её закрытия. Вертикальные линии — медиана (P50) и P90. Длинный «хвост» справа — задачи, которые жили очень долго.")
        ro = dff[dff["resolution_date"].notna()].copy()
        ro["lifetime"] = (ro["resolution_date"] - ro["created"]).dt.total_seconds() / 86400
        ro = ro[(ro["lifetime"] >= 0) & (ro["lifetime"] < 2000)]

        if len(ro) > 0:
            fig = px.histogram(ro, x="lifetime", nbins=60,
                               labels={"lifetime": "Дни"}, color_discrete_sequence=["#636EFA"])
            fig.update_layout(height=350, xaxis_title="Дни", yaxis_title="Кол-во задач")
            p50 = safe_pct(ro["lifetime"], 50)
            p90 = safe_pct(ro["lifetime"], 90)
            fig.add_vline(x=p50, line_dash="dash", line_color="red",
                          annotation_text=f"P50={p50:.0f}д")
            fig.add_vline(x=p90, line_dash="dash", line_color="orange",
                          annotation_text=f"P90={p90:.0f}д")
            st.plotly_chart(fig, use_container_width=True)

            st.markdown(f"""
            **P10:** {safe_pct(ro['lifetime'], 10):.0f} дней | 
            **P50 (медиана):** {p50:.0f} дней | 
            **P75:** {safe_pct(ro['lifetime'], 75):.0f} дней | 
            **P90:** {p90:.0f} дней | 
            **P95:** {safe_pct(ro['lifetime'], 95):.0f} дней
            """)

        # ---- New department-level metrics ----

        # Cycle Time Trend
        st.markdown("---")
        st.markdown("### 📉 Тренд cycle time (P50/P90 по месяцам)")
        st.caption("Медианное (P50) и 90-й перцентиль (P90) время от создания до закрытия по месяцам. Тренд вниз = ускоряемся, вверх = замедляемся. MA3 сглаживает выбросы.")
        ct_trend = calc_cycle_time_trend(dff)
        if len(ct_trend) > 0:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=ct_trend["ym"], y=ct_trend["p50"], name="P50", line=dict(color="#636EFA", width=2)))
            fig.add_trace(go.Scatter(x=ct_trend["ym"], y=ct_trend["p50_ma"], name="P50 (MA3)", line=dict(color="#636EFA", width=2, dash="dot")))
            fig.add_trace(go.Scatter(x=ct_trend["ym"], y=ct_trend["p90"], name="P90", line=dict(color="#EF553B", width=2)))
            fig.add_trace(go.Scatter(x=ct_trend["ym"], y=ct_trend["p90_ma"], name="P90 (MA3)", line=dict(color="#EF553B", width=2, dash="dot")))
            fig.update_layout(height=350, xaxis_title="Месяц закрытия", yaxis_title="Дни",
                              legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет закрытых задач для тренда.")

        # Queue Time vs Process Time
        st.markdown("### ⚖️ Время в очереди vs время в работе")
        st.caption("Медианное время в To Do (очередь) и в In Progress (работа) по месяцам закрытия. Если растёт очередь — проблема в приоритизации. Если растёт время работы — проблема в исполнении.")
        qp = calc_queue_vs_process(dff, bl_df, ip_df)
        if len(qp) > 0:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=qp["ym"], y=qp["queue"], name="Очередь (To Do)", marker_color="#636EFA", opacity=0.5))
            fig.add_trace(go.Bar(x=qp["ym"], y=qp["process"], name="Работа (In Progress)", marker_color="#FFA500", opacity=0.5))
            fig.add_trace(go.Scatter(x=qp["ym"], y=qp["queue_ma"], name="Очередь (MA3)", line=dict(color="#636EFA", width=2)))
            fig.add_trace(go.Scatter(x=qp["ym"], y=qp["process_ma"], name="Работа (MA3)", line=dict(color="#FFA500", width=2)))
            fig.update_layout(barmode="group", height=350, xaxis_title="Месяц закрытия", yaxis_title="Медианные дни",
                              legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет данных для разбивки queue vs process.")

        # Time in Review (combined: In Review + In review (Design))
        st.markdown("### 🔍 Время в ревью (In Review + In review Design)")
        st.caption("Медианное время в статусах ревью (In Review и In review Design суммарно по задаче). Объединённая метрика: если задача прошла оба статуса, время суммируется. Высокие значения = узкое место в согласовании.")
        rev_all = calc_time_in_status(dff, dft_f, ["In Review", "In review (Design)"])
        col_r1, col_r2, col_r3 = st.columns(3)
        med_rev = rev_all["status_days"].median() if len(rev_all) > 0 else 0
        mean_rev = rev_all["status_days"].mean() if len(rev_all) > 0 else 0
        col_r1.metric("Медиана времени в ревью", f"{med_rev:.1f}д" if med_rev else "—",
                       help="Медианное суммарное время в статусах In Review + In review (Design)")
        col_r2.metric("Среднее время в ревью", f"{mean_rev:.1f}д" if mean_rev else "—",
                       help="Среднее суммарное время в ревью")
        col_r3.metric("Задач с ревью", len(rev_all))

        rev_trend = calc_review_time_trend(dff, dft_f, ["In Review", "In review (Design)"], "Review")
        if len(rev_trend) > 0:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=rev_trend["ym"], y=rev_trend["median_days"],
                                 name="Медиана (дни)", marker_color="#636EFA", opacity=0.6))
            fig.add_trace(go.Scatter(x=rev_trend["ym"], y=rev_trend["median_ma"],
                                     name="MA3", line=dict(color="#EF553B", width=2)))
            fig.update_layout(height=350, xaxis_title="Месяц закрытия", yaxis_title="Дни",
                              legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет данных о времени в ревью.")

        # Flow Efficiency
        st.markdown("### ⚡ Flow Efficiency (эффективность потока)")
        st.caption("Доля активного времени в работе от общего lead time. 100% = задача сразу взята в работу и закрыта. Низкий % = задачи долго лежат в очередях. Медиана по отделу показана в KPI.")
        resolved_eff = dff[dff["resolution_date"].notna()].copy()
        if len(resolved_eff) > 0:
            resolved_eff["lifetime"] = (resolved_eff["resolution_date"] - resolved_eff["created"]).dt.total_seconds() / 86400
            resolved_eff = resolved_eff[(resolved_eff["lifetime"] > 0) & (resolved_eff["lifetime"] < 2000)]
            eff_merged = resolved_eff.merge(ip_df, on="key", how="left")
            eff_merged["efficiency"] = (eff_merged["in_progress_days"] / eff_merged["lifetime"] * 100).clip(0, 100)
            eff_valid = eff_merged.dropna(subset=["efficiency"])
            if len(eff_valid) > 0:
                med_eff = eff_valid["efficiency"].median()
                col_fe1, col_fe2, col_fe3 = st.columns(3)
                col_fe1.metric("Медиана efficiency", f"{med_eff:.0f}%")
                col_fe2.metric("P25", f"{safe_pct(eff_valid['efficiency'], 25):.0f}%")
                col_fe3.metric("P75", f"{safe_pct(eff_valid['efficiency'], 75):.0f}%")

                fig = px.histogram(eff_valid, x="efficiency", nbins=30,
                                   labels={"efficiency": "Flow Efficiency (%)"},
                                   color_discrete_sequence=["#00CC96"])
                fig.update_layout(height=300, xaxis_title="Flow Efficiency (%)", yaxis_title="Кол-во задач")
                fig.add_vline(x=med_eff, line_dash="dash", line_color="red", annotation_text=f"Медиана={med_eff:.0f}%")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет данных для расчёта эффективности.")
        else:
            st.info("Нет закрытых задач.")

        # On-time Delivery
        st.markdown("### 🎯 On-time Delivery (доля задач по сроку)")
        st.caption("Процент задач, закрытых до указанного due_date. Единственная метрика, прямо отвечающая на «выполняем ли обещания». Только задачи с заполненным due_date.")
        otd = calc_on_time_delivery(dff)
        if len(otd) > 0:
            total_due = otd["total"].sum()
            total_on = int(otd["on_time"].sum())
            overall_pct = total_on / total_due * 100 if total_due > 0 else 0
            col_otd1, col_otd2, col_otd3 = st.columns(3)
            col_otd1.metric("Задач с due_date", total_due)
            col_otd2.metric("Закрыто вовремя", total_on)
            col_otd3.metric("On-time rate", f"{overall_pct:.0f}%")

            otd_show = otd[otd["ym"] >= "2020-01"]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=otd_show["ym"], y=otd_show["pct"], name="On-time %", marker_color="#AB63FA", opacity=0.5))
            fig.add_trace(go.Scatter(x=otd_show["ym"], y=otd_show["pct"].rolling(3, min_periods=1).mean(),
                                     name="MA3", line=dict(color="#7C3AED", width=2)))
            fig.update_layout(height=300, xaxis_title="Месяц закрытия", yaxis_title="% по сроку",
                              legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет задач с due_date в выборке.")

        # Predictability
        st.markdown("---")
        st.markdown("### 🎯 Predictability (предсказуемость)")
        st.caption("Коэффициент вариации (CV = std/mean) месячного throughput закрытых задач. CV < 0.3 = стабильный отдел. CV > 0.5 = хаотичный throughput, нельзя планировать.")
        pred = calc_predictability(dff)
        if pred is not None:
            cv = pred["cv"]
            mean_tp = pred["mean"]
            std_tp = pred["std"]
            col_p1, col_p2, col_p3 = st.columns(3)
            col_p1.metric("Средний throughput", f"{mean_tp:.0f} задач/мес")
            col_p2.metric("Std dev", f"{std_tp:.0f}")
            cv_color = "🟢" if cv < 0.3 else ("🟡" if cv < 0.5 else "🔴")
            col_p3.metric("CV (предсказуемость)", f"{cv:.2f} {cv_color}")
            monthly_data = pred["monthly"]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=list(monthly_data.keys()), y=list(monthly_data.values()),
                                 name="Закрыто/мес", marker_color="#636EFA", opacity=0.5))
            fig.add_hline(y=mean_tp, line_dash="dash", line_color="red", annotation_text=f"Mean={mean_tp:.0f}")
            fig.update_layout(height=300, xaxis_title="Месяц", yaxis_title="Закрыто задач")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Недостаточно данных для расчёта предсказуемости.")

        # Rework Trend
        st.markdown("### 📉 Тренд rework rate")
        st.caption("Доля задач с обратными переходами (rework) по месяцам. Тренд вниз = качество улучшается, вверх = деградирует.")
        rw_trend = calc_rework_trend(dft_f, smap)
        if len(rw_trend) > 0:
            rw_show = rw_trend[rw_trend["ym"] >= "2020-01"]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=rw_show["ym"], y=rw_show["pct"], name="Rework %", marker_color="#EF553B", opacity=0.5))
            fig.add_trace(go.Scatter(x=rw_show["ym"], y=rw_show["pct_ma"], name="MA3", line=dict(color="#C0392B", width=2)))
            fig.update_layout(height=300, xaxis_title="Месяц", yaxis_title="% rework",
                              legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет данных для тренда rework.")

        # First-Time-Right Rate
        st.markdown("---")
        st.markdown("### 🎯 First-Time-Right (с первого раза правильно)")
        st.caption("Доля закрытых задач, которые дошли до Done без единого возврата (backward transition). Высокий % = качество сдачи хорошее, низкий = задачи переделываются по несколько раз.")
        ftr_count, ftr_total, ftr_trend = calc_first_time_right(dff, dft_f, smap)
        if ftr_total > 0:
            ftr_pct = ftr_count / ftr_total * 100
            col_ftr1, col_ftr2, col_ftr3 = st.columns(3)
            col_ftr1.metric("Закрыто всего", ftr_total)
            col_ftr2.metric("С первого раза", ftr_count)
            ftr_color = "🟢" if ftr_pct >= 70 else ("🟡" if ftr_pct >= 50 else "🔴")
            col_ftr3.metric("FTR rate", f"{ftr_pct:.0f}% {ftr_color}")
            if len(ftr_trend) > 0:
                ftr_show = ftr_trend[ftr_trend["ym"] >= "2020-01"]
                fig = go.Figure()
                fig.add_trace(go.Bar(x=ftr_show["ym"], y=ftr_show["pct"], name="FTR %", marker_color="#00CC96", opacity=0.5))
                fig.add_trace(go.Scatter(x=ftr_show["ym"], y=ftr_show["pct_ma"], name="MA3", line=dict(color="#0A6C4D", width=2)))
                fig.update_layout(height=300, xaxis_title="Месяц закрытия", yaxis_title="% FTR",
                                  legend=dict(orientation="h", y=1.12))
                st.plotly_chart(fig, use_container_width=True)

        # Review Reject Rate
        st.markdown("### 🔍 Review Reject Rate (возвраты из ревью)")
        st.caption("Сколько задач вернулось из ревью (In Review / In review Design) обратно в работу. Высокий % = проблемы с качеством сдачи, не со скоростью ревью.")
        rej_count, rej_total, rej_pct, rej_trend = calc_review_reject_rate(dft_f)
        if rej_total > 0:
            col_rej1, col_rej2, col_rej3 = st.columns(3)
            col_rej1.metric("Задач в ревью", rej_total)
            col_rej2.metric("Вернулось в работу", rej_count)
            col_rej3.metric("Reject rate", f"{rej_pct:.0f}%")
            if len(rej_trend) > 0:
                rej_show = rej_trend[rej_trend["ym"] >= "2020-01"]
                fig = go.Figure()
                fig.add_trace(go.Bar(x=rej_show["ym"], y=rej_show["pct"], name="Reject %", marker_color="#EF553B", opacity=0.5))
                fig.add_trace(go.Scatter(x=rej_show["ym"], y=rej_show["pct_ma"], name="MA3", line=dict(color="#C0392B", width=2)))
                fig.update_layout(height=300, xaxis_title="Месяц", yaxis_title="% rejected",
                                  legend=dict(orientation="h", y=1.12))
                st.plotly_chart(fig, use_container_width=True)

        # ---- Year-over-Year comparisons ----
        st.markdown("---")
        st.markdown("### 📅 Year-over-Year: сравнение по месяцам")
        st.caption("Сравнение ключевых метрик по месяцам, год к году. Каждый год — отдельная линия, ось X — номер месяца (1=январь, 12=декабрь). Позволяет ответить на вопрос «в этом месяце мы лучше или хуже, чем в том же месяце прошлого года?». Убирает сезонность: если cycle time в августе растёт каждый год — это паттерн, а не разовая проблема. Выберите метрику из списка — доступны все трендовые метрики с разбивкой по месяцам.")

        # Compute est_trend here (before YoY) to avoid UnboundLocalError —
        # it's also computed later in Tab 3, but YoY needs it first.
        est_trend = calc_estimation_trend(dff)

        yoy_data = [
            ("Cycle time (P50)", ct_trend, "p50", "Дни"),
            ("Cycle time (P90)", ct_trend, "p90", "Дни"),
            ("Очередь (To Do)", qp, "queue", "Дни"),
            ("Работа (In Progress)", qp, "process", "Дни"),
            ("Время в ревью", rev_trend, "median_days", "Дни"),
            ("Rework %", rw_trend, "pct", "% rework"),
            ("On-time %", otd, "pct", "% по сроку"),
            ("Review Reject %", rej_trend, "pct", "% rejected"),
            ("Точность оценок (mean ratio)", est_trend, "mean_ratio", "Факт/Оценка"),
        ]

        yoy_labels = [d[0] for d in yoy_data]
        yoy_sel = st.selectbox("Выберите метрику для YoY сравнения", yoy_labels, index=0)
        yoy_idx = yoy_labels.index(yoy_sel)
        yoy_label, yoy_df, yoy_col, yoy_ytitle = yoy_data[yoy_idx]

        if yoy_df is not None and len(yoy_df) > 0:
            pivot = reshape_yoy(yoy_df, "ym", yoy_col)
            if len(pivot) > 0:
                fig = go.Figure()
                year_cols = [c for c in pivot.columns if c != "month"]
                colors = px.colors.qualitative.Set2
                for i, yr in enumerate(sorted(year_cols)):
                    yy = pivot[["month", yr]].dropna()
                    if len(yy) > 0:
                        fig.add_trace(go.Scatter(
                            x=yy["month"], y=yy[yr], name=str(yr),
                            mode="lines+markers",
                            line=dict(color=colors[i % len(colors)], width=2)))
                fig.update_layout(height=400, xaxis_title="Месяц", yaxis_title=yoy_ytitle,
                                  legend=dict(orientation="h", y=1.12),
                                  xaxis=dict(dtick=1, tickmode="linear"))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Недостаточно данных для YoY сравнения.")
        else:
            st.info("Нет данных для этой метрики.")

    # ===================== TAB 3: PEOPLE =====================
    with tab3:
        st.markdown("## 👥 Люди")
        st.caption("Анализ нагрузки по исполнителям: кто закрывает больше, распределение задач во времени, учёт рабочего времени и процент задач с логированием.")

        col_c, col_d = st.columns(2)

        with col_c:
            st.markdown("### 👤 Топ исполнителей (created vs resolved)")
            st.caption("Сколько задач назначено на каждого исполнителя (синий) и сколько из них закрыто (зелёный). Сортировка по общему количеству.")
            ta = dff[dff["assignee_name"].notna()].groupby("assignee_name").agg(
                total=("key", "count"),
                resolved=("resolution", lambda x: x.notna().sum()),
            ).reset_index().sort_values("total", ascending=True).tail(15)
            fig = go.Figure()
            fig.add_trace(go.Bar(y=ta["assignee_name"], x=ta["total"],
                                 name="Всего", orientation="h", marker_color="#636EFA"))
            fig.add_trace(go.Bar(y=ta["assignee_name"], x=ta["resolved"],
                                 name="Закрыто", orientation="h", marker_color="#2CA02C"))
            fig.update_layout(barmode="overlay", height=450)
            st.plotly_chart(fig, use_container_width=True)

        with col_d:
            st.markdown("### 🗓️ Heatmap: задачи по месяцам (топ-15)")
            st.caption("Тепловая карта: сколько задач создавалось в месяц для топ-15 исполнителей. Чем темнее, тем больше нагрузка в этом месяце. Показаны последние 24 месяца.")
            top_a = dff[dff["assignee_name"].notna()]["assignee_name"].value_counts().head(15).index
            hm = dff[dff["assignee_name"].isin(top_a)].copy()
            hm["ym"] = hm["created"].dt.to_period("M").astype(str)
            pivot = hm.groupby(["assignee_name", "ym"]).size().unstack(fill_value=0)
            # Limit to last 24 months for readability
            recent_cols = sorted(pivot.columns)[-24:]
            pivot = pivot[recent_cols]
            fig = px.imshow(pivot, labels=dict(x="Месяц", y="", color="Задач"),
                            color_continuous_scale="YlOrRd", aspect="auto")
            fig.update_layout(height=450)
            st.plotly_chart(fig, use_container_width=True)

        # Time logging
        st.markdown("---")
        st.markdown("## ⏱️ Учёт времени")
        st.caption("Сколько рабочего времени логируется в Jira, кто логирует и как это меняется во времени. «Логирование» = ведение учёта времени (worklog) по задачам.")

        if len(dfw) > 0:
            wl = dfw.copy()
            wl["started"] = pd.to_datetime(wl["started"], errors="coerce")
            wl = wl.dropna(subset=["author_name"])

            # Filter worklogs to filtered issues
            wl_f = wl[wl["issue_key"].isin(dff["key"])] if "key" in dff.columns else wl

            tbp = wl_f.groupby("author_name").agg(
                entries=("issue_key", "count"),
                total_sec=("time_spent_seconds", "sum"),
                issues=("issue_key", "nunique"),
            ).reset_index()
            tbp["hours"] = (tbp["total_sec"] / 3600).round(1)
            tbp = tbp.sort_values("hours", ascending=True).tail(15)

            col_e, col_f2 = st.columns(2)
            with col_e:
                st.markdown("### ⏳ Время по людям (часы)")
                st.caption("Сумма залогированных часов по каждому сотруднику. Топ-15 по объёму.")
                fig = px.bar(tbp, x="hours", y="author_name", orientation="h",
                             labels={"hours": "Часы", "author_name": ""},
                             color="hours", color_continuous_scale="Sunset")
                fig.update_layout(height=450, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

            with col_f2:
                st.markdown("### 📝 Логирование по месяцам")
                st.caption("Сколько часов залогировано в каждом месяце. Позволяет оценить динамику и сезонность учёта времени.")
                wl_f2 = wl_f.dropna(subset=["started"]).copy()
                wl_f2["ym"] = wl_f2["started"].dt.to_period("M").astype(str)
                wlm = wl_f2.groupby("ym").agg(entries=("issue_key", "count"),
                                               hours=("time_spent_seconds", lambda x: x.sum() / 3600)).reset_index()
                wlm = wlm[wlm["ym"] >= "2020-01"]
                fig = px.bar(wlm, x="ym", y="hours", labels={"ym": "Месяц", "hours": "Часы"},
                             color="hours", color_continuous_scale="Sunset")
                fig.update_layout(height=450, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

            st.markdown("### Детализация времени")
            st.caption("Таблица: сотрудник, количество записей о времени, количество затронутых задач, суммарные часы.")
            st.dataframe(tbp[["author_name", "entries", "issues", "hours"]].sort_values("hours", ascending=False),
                         use_container_width=True, hide_index=True)

        # Worklog coverage by person — enhanced with overall KPIs and detailed table
        st.markdown("---")
        st.markdown("### 📊 Worklog coverage: процент задач с логированием")
        st.caption("Какой процент задач каждого исполнителя имеет хотя бы одну запись о времени (worklog). Общий процент по всей выборке показан в KPI блоке ниже.")
        assigned = dff[dff["assignee_name"].notna()].copy()
        wl_issues = set(dfw["issue_key"].unique()) if len(dfw) > 0 else set()
        assigned["has_wl"] = assigned["key"].isin(wl_issues)
        cov = assigned.groupby("assignee_name").agg(
            total=("key", "count"),
            with_wl=("has_wl", "sum"),
        ).reset_index()
        cov["pct"] = (cov["with_wl"] / cov["total"] * 100).round(0)
        cov = cov.sort_values("total", ascending=False).head(20)
        cov = cov.sort_values("pct", ascending=True)

        # Overall coverage KPI
        total_assigned = len(assigned)
        total_with_wl = int(assigned["has_wl"].sum())
        overall_pct = (total_with_wl / total_assigned * 100) if total_assigned > 0 else 0
        col_cov1, col_cov2, col_cov3 = st.columns(3)
        col_cov1.metric("Всего задач с исполнителем", total_assigned)
        col_cov2.metric("Из них с логированием", total_with_wl)
        col_cov3.metric("Общий coverage", f"{overall_pct:.0f}%")

        col_chart, col_table = st.columns([3, 2])
        with col_chart:
            fig = go.Figure()
            fig.add_trace(go.Bar(y=cov["assignee_name"], x=cov["pct"], orientation="h",
                                 name="% с логированием", marker_color="#FFA500",
                                 text=cov["pct"].apply(lambda x: f"{x:.0f}%"),
                                 textposition="outside"))
            fig.update_layout(height=500, xaxis_title="% задач с логированием", yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)
        with col_table:
            st.markdown("**Детальная таблица**")
            st.dataframe(
                cov[["assignee_name", "total", "with_wl", "pct"]].rename(
                    columns={"assignee_name": "Исполнитель", "total": "Всего",
                             "with_wl": "С логир.", "pct": "%"}
                ).sort_values("%", ascending=False),
                use_container_width=True, hide_index=True, height=500)

        # ---- Per-person metrics ----
        st.markdown("---")
        st.markdown("## 📊 Метрики по сотрудникам")
        st.caption("Индивидуальные метрики: скорость, объём, качество, предсказуемость. Только исполнители с ≥5 задачами в выборке.")

        col_p1, col_p2 = st.columns(2)

        with col_p1:
            # Cycle Time per Person
            st.markdown("### ⚡ Cycle time по людям (медиана P50/P90)")
            st.caption("Медианное время от создания до закрытия задачи по каждому исполнителю. Меньше = быстрее. P90 показывает «хвост». Только исполнители с ≥5 закрытыми задачами.")
            ct_person = calc_cycle_time_per_person(dff)
            if len(ct_person) > 0:
                ct_show = ct_person.sort_values("median_cycle", ascending=True).tail(15)
                fig = go.Figure()
                fig.add_trace(go.Bar(y=ct_show["assignee_name"], x=ct_show["median_cycle"],
                                     name="P50", orientation="h", marker_color="#636EFA"))
                fig.add_trace(go.Bar(y=ct_show["assignee_name"], x=ct_show["p90_cycle"],
                                     name="P90", orientation="h", marker_color="#EF553B", opacity=0.5))
                fig.update_layout(barmode="overlay", height=400, xaxis_title="Дни", yaxis_title="",
                                  legend=dict(orientation="h", y=1.12))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет данных.")

        with col_p2:
            # Throughput per Person
            st.markdown("### 📦 Throughput по людям (закрытые задачи)")
            st.caption("Сколько задач закрыл каждый сотрудник за весь период выборки. Топ-15 по количеству.")
            tp_person = dff[dff["resolution_date"].notna() & dff["assignee_name"].notna()].copy()
            if len(tp_person) > 0:
                closed_counts = tp_person.groupby("assignee_name").size().reset_index(name="closed")
                closed_counts = closed_counts.sort_values("closed", ascending=True).tail(15)
                fig = px.bar(closed_counts, x="closed", y="assignee_name", orientation="h",
                             labels={"closed": "Закрыто", "assignee_name": ""},
                             color="closed", color_continuous_scale="Viridis")
                fig.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет данных.")

        # Hours vs Tasks
        st.markdown("### ⏱️ Залогированные часы vs закрытые задачи по людям")
        st.caption("Сравнение: сколько часов залогировано (оранжевый) и сколько задач закрыто (зелёный). Если часов много, а задач мало — человек застрял на сложных задачах. Если наоборот — задачи тривиальные. Топ-15 по закрытым.")
        ht = calc_hours_vs_tasks(dff, dfw)
        if len(ht) > 0:
            ht = ht.sort_values("tasks", ascending=True).tail(15)
            fig = go.Figure()
            fig.add_trace(go.Bar(y=ht["assignee_name"], x=ht["hours"], name="Часы",
                                 orientation="h", marker_color="#FF9F43"))
            fig.add_trace(go.Bar(y=ht["assignee_name"], x=ht["tasks"], name="Задачи",
                                 orientation="h", marker_color="#2CA02C"))
            fig.update_layout(barmode="group", height=450, xaxis_title="Часы / Кол-во задач", yaxis_title="",
                              legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, use_container_width=True)

        col_pp1, col_pp2 = st.columns(2)

        with col_pp1:
            # Rework per Person
            st.markdown("### 🔁 Rework rate по людям")
            st.caption("Процент задач каждого исполнителя, вернувшихся на доработку. Чем выше — тем чаще требуется переделка. Только исполнители с ≥5 задачами.")
            rw_person = calc_rework_per_person(dff, dft_f, smap)
            if len(rw_person) > 0:
                rw_top = rw_person.sort_values("pct", ascending=True).tail(15)
                fig = px.bar(rw_top, x="pct", y="assignee_name", orientation="h",
                             labels={"pct": "% rework", "assignee_name": ""},
                             color="pct", color_continuous_scale="Sunset")
                fig.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет данных по rework.")

        with col_pp2:
            # Estimation Accuracy per Person
            st.markdown("### 📐 Точность оценок по людям")
            st.caption("Средний ratio (факт/оценка) по каждому исполнителю. 1.0 = идеальная оценка. >1 = недооценивает, <1 = переоценивает. Только исполнители с ≥3 задачами с оценкой.")
            ea_person = calc_estimation_per_person(dff)
            if len(ea_person) > 0:
                ea_top = ea_person.sort_values("mean_ratio", ascending=True).tail(15)
                fig = px.bar(ea_top, x="mean_ratio", y="assignee_name", orientation="h",
                             labels={"mean_ratio": "Факт/Оценка", "assignee_name": ""},
                             color="mean_ratio", color_continuous_scale="RdYlGn_r")
                fig.update_layout(height=400, showlegend=False)
                fig.add_vline(x=1.0, line_dash="dash", line_color="red")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет данных по оценкам.")

        col_pp3, col_pp4 = st.columns(2)

        with col_pp3:
            # Stale WIP per Person
            st.markdown("### 🧊 Зависшие задачи по людям")
            st.caption("Сколько незакрытых задач без движения у каждого исполнителя. Высокий count = человек «держит» невыполненные задачи.")
            stale_person = calc_stale_per_person(dff, dft_f)
            if len(stale_person) > 0:
                sp = stale_person.sort_values("stale_count", ascending=True).tail(15)
                fig = px.bar(sp, x="stale_count", y="assignee_name", orientation="h",
                             labels={"stale_count": "Зависших задач", "assignee_name": ""},
                             color="stale_count", color_continuous_scale="IceFire")
                fig.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет зависших задач.")

        with col_pp4:
            # Concurrent WIP per Person
            st.markdown("### 🔄 Concurrent WIP по людям")
            st.caption("Сколько задач сейчас в работе (In Progress) у каждого исполнителя. Высокий WIP (5+) = context switching = снижение продуктивности. В идеале 1–3 задачи.")
            cwip = calc_concurrent_wip_per_person(dff)
            if len(cwip) > 0:
                cwip = cwip.sort_values("wip_count", ascending=True).tail(15)
                fig = px.bar(cwip, x="wip_count", y="assignee_name", orientation="h",
                             labels={"wip_count": "Задач в работе", "assignee_name": ""},
                             color="wip_count", color_continuous_scale="Plasma")
                fig.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет задач в работе.")

        # Review Time per Person (combined: In Review + In review (Design))
        st.markdown("### 🔍 Время в ревью по людям")
        st.caption("Медианное суммарное время в статусах In Review + In review (Design) по исполнителям (≥3 задач). Показывает, у кого задачи застревают на ревью дольше всего.")
        rev_pp = calc_review_time_per_person(dff, dft_f, ["In Review", "In review (Design)"])
        if len(rev_pp) > 0:
            fig = px.bar(rev_pp.tail(15), x="median_days", y="assignee_name",
                         orientation="h",
                         labels={"median_days": "Медиана, дни", "assignee_name": ""},
                         color="median_days", color_continuous_scale="Blues")
            fig.update_layout(height=400, showlegend=False,
                              coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет данных о времени в ревью по людям.")

        # Throughput per person heatmap (closed tasks)
        st.markdown("### 🗓️ Тепловая карта: закрытые задачи по месяцам")
        st.caption("Тепловая карта: сколько задач закрыл каждый сотрудник (топ-15) помесячно. Чем темнее — тем больше закрытых. Видна динамика и сезонность каждого.")
        tp_heat = dff[dff["resolution_date"].notna() & dff["assignee_name"].notna()].copy()
        if len(tp_heat) > 0:
            tp_heat["ym"] = tp_heat["resolution_date"].dt.to_period("M").astype(str)
            top_closed = tp_heat["assignee_name"].value_counts().head(15).index
            hc = tp_heat[tp_heat["assignee_name"].isin(top_closed)]
            pivot = hc.groupby(["assignee_name", "ym"]).size().unstack(fill_value=0)
            recent = sorted(pivot.columns)[-24:]
            pivot = pivot[recent]
            fig = px.imshow(pivot, labels=dict(x="Месяц", y="", color="Закрыто"),
                            color_continuous_scale="Greens", aspect="auto")
            fig.update_layout(height=450)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет данных по закрытым задачам.")

    # ===================== TAB 4: DEEP DIVES =====================
    with tab4:
        st.markdown("## 🔬 Deep Dives")
        st.caption("Глубокий анализ: покрытие логированием, время в бэклоге, время до назначения, «зависшие» задачи, процент возвратов (rework), точность оценок и самые «крутящиеся» задачи.")

        # Worklog coverage by project
        st.markdown("### 📊 Worklog coverage по проектам")
        st.caption("Процент задач в каждом проекте, по которым залогировано хотя бы немного времени. Низкий процент означает, что учёт времени в проекте не ведётся системно.")
        wl_issues = set(dfw["issue_key"].unique()) if len(dfw) > 0 else set()
        dff_wl = dff.copy()
        dff_wl["has_wl"] = dff_wl["key"].isin(wl_issues)
        pcov = dff_wl.groupby("project_key").agg(
            total=("key", "count"),
            with_wl=("has_wl", "sum"),
        ).reset_index()
        pcov["pct"] = (pcov["with_wl"] / pcov["total"] * 100).round(1)
        pcov = pcov.sort_values("pct", ascending=True)
        fig = go.Figure()
        fig.add_trace(go.Bar(y=pcov["project_key"], x=pcov["pct"], orientation="h",
                             name="% с логированием", marker_color="#636EFA",
                             text=pcov["pct"].apply(lambda x: f"{x}%"),
                             textposition="outside"))
        fig.update_layout(height=350, xaxis_title="% задач с logged time", yaxis_title="Проект")
        st.plotly_chart(fig, use_container_width=True)

        col_g, col_h = st.columns(2)

        with col_g:
            # Time in backlog
            st.markdown("### 📦 Время в бэклоге (To Do)")
            st.caption("Сколько дней каждая задача провела в статусе To Do до перехода в работу. Длинный хвост = задачи подолгу лежат без движения.")
            bl_valid = bl_df.dropna(subset=["backlog_days"])
            bl_valid = bl_valid[(bl_valid["backlog_days"] >= 0) & (bl_valid["backlog_days"] < 365 * 3)]
            if len(bl_valid) > 0:
                fig = px.histogram(bl_valid, x="backlog_days", nbins=50,
                                   labels={"backlog_days": "Дни в бэклоге"},
                                   color_discrete_sequence=["#FF6B6B"])
                fig.update_layout(height=350, xaxis_title="Дни", yaxis_title="Кол-во задач")
                p50 = safe_pct(bl_valid["backlog_days"], 50)
                p75 = safe_pct(bl_valid["backlog_days"], 75)
                p90 = safe_pct(bl_valid["backlog_days"], 90)
                fig.add_vline(x=p50, line_dash="dash", line_color="red",
                              annotation_text=f"P50={p50:.0f}д")
                fig.add_vline(x=p90, line_dash="dash", line_color="orange",
                              annotation_text=f"P90={p90:.0f}д")
                st.plotly_chart(fig, use_container_width=True)
                st.markdown(f"""
                **P50:** {p50:.0f}д | **P75:** {p75:.0f}д | **P90:** {p90:.0f}д | 
                **Среднее:** {bl_valid['backlog_days'].mean():.0f}д
                """)

        with col_h:
            # Time to first assignment
            st.markdown("### ⏱️ Time to first assignment")
            st.caption("Сколько дней от создания задачи до первого назначения исполнителя. Высокие значения = задачи долго висят без хозяина.")
            tta = calc_time_to_assign(dff, dfc)
            tta_valid = tta[tta["days_to_assign"] < 365]  # filter outliers
            if len(tta_valid) > 0:
                fig = px.histogram(tta_valid, x="days_to_assign", nbins=50,
                                   labels={"days_to_assign": "Дни до назначения"},
                                   color_discrete_sequence=["#9467BD"])
                fig.update_layout(height=350, xaxis_title="Дни", yaxis_title="Кол-во задач")
                p50 = safe_pct(tta_valid["days_to_assign"], 50)
                p90 = safe_pct(tta_valid["days_to_assign"], 90)
                fig.add_vline(x=p50, line_dash="dash", line_color="red",
                              annotation_text=f"P50={p50:.0f}д")
                fig.add_vline(x=p90, line_dash="dash", line_color="orange",
                              annotation_text=f"P90={p90:.0f}д")
                st.plotly_chart(fig, use_container_width=True)
                st.markdown(f"""
                **P50:** {p50:.0f}д | **P90:** {p90:.0f}д | 
                **Среднее:** {tta_valid['days_to_assign'].mean():.0f}д
                """)
            else:
                st.info("Нет данных о назначении исполнителей.")

        # Stale tasks
        st.markdown("---")
        st.markdown("### 🧊 Застоявшиеся задачи (Aging WIP)")
        st.caption("Незакрытые задачи, по которым давно не было смены статуса. Чем больше дней без движения — тем «застарелее» задача. Пороги: >30, >60, >90 дней.")
        stale = calc_stale(dff, dft_f)
        if len(stale) > 0 and stale["days_stale"].notna().any():
            stale_show = stale.dropna(subset=["days_stale"])
            stale_show = stale_show.sort_values("days_stale", ascending=False)

            # Summary stats
            s30 = (stale_show["days_stale"] > 30).sum()
            s60 = (stale_show["days_stale"] > 60).sum()
            s90 = (stale_show["days_stale"] > 90).sum()
            st.markdown(f"""
            Задач без движения: **{len(stale_show)}** | 
            >30 дней: **{s30}** | >60 дней: **{s60}** | >90 дней: **{s90}**
            """)

            # Bar chart: stale by status
            sb = stale_show.groupby("status").agg(
                count=("key", "count"),
                avg_days=("days_stale", "mean"),
                max_days=("days_stale", "max"),
            ).reset_index().sort_values("avg_days", ascending=True)
            fig = px.bar(sb, x="avg_days", y="status", orientation="h",
                         labels={"avg_days": "Средние дни без движения", "status": ""},
                         color="avg_days", color_continuous_scale="IceFire")
            fig.update_layout(height=300, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

            show_cols = ["key", "project_key", "summary", "status", "assignee_name", "days_stale"]
            avail = [c for c in show_cols if c in stale_show.columns]
            st.dataframe(stale_show[avail].head(20), use_container_width=True, hide_index=True)

        # Rework rate
        st.markdown("---")
        st.markdown("### 🔄 Rework rate (задачи, вернувшиеся назад)")
        st.caption("Сколько задач вернулось на более раннюю стадию (например, из Done обратно в In Progress). Высокий процент сигнализирует о проблемах с качеством или требованиями.")
        rw_count, rw_total = calc_rework(dft_f, smap)
        if rw_total > 0:
            rw_pct = rw_count / rw_total * 100
            col_r1, col_r2, col_r3 = st.columns(3)
            col_r1.metric("Задач с переходами", rw_total)
            col_r2.metric("С rework", rw_count)
            col_r3.metric("Rework rate", f"{rw_pct:.1f}%")

        # Estimation accuracy
        st.markdown("---")
        st.markdown("### 📐 Estimation accuracy (оценка vs факт)")
        st.caption("Сравнение изначальной оценки (original estimate) и фактически затраченного времени. Точки на красной линии = идеальная оценка. Выше линии — недооценка, ниже — переоценка.")
        est = dff[(dff["original_estimate"].notna()) & (dff["time_spent"].notna()) &
                   (dff["original_estimate"] > 0) & (dff["time_spent"] > 0)].copy()
        if len(est) > 0:
            est["ratio"] = est["time_spent"] / est["original_estimate"]
            est["est_hours"] = est["original_estimate"] / 3600
            est["actual_hours"] = est["time_spent"] / 3600

            fig = px.scatter(est, x="est_hours", y="actual_hours",
                             hover_data=["key"], opacity=0.5,
                             labels={"est_hours": "Оценка (часы)", "actual_hours": "Факт (часы)"},
                             color_discrete_sequence=["#636EFA"])
            max_val = max(est["est_hours"].max(), est["actual_hours"].max())
            fig.add_trace(go.Scatter(x=[0, max_val], y=[0, max_val], mode="lines",
                                     name="Идеальная оценка", line=dict(dash="dash", color="red")))
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)

            under = (est["ratio"] > 1.5).sum()
            over = (est["ratio"] < 0.5).sum()
            st.markdown(f"""
            **Всего с оценкой и фактом:** {len(est)} задач | 
            **Недооценено (>1.5×):** {under} | 
            **Переоценено (<0.5×):** {over} | 
            **Средний ratio:** {est['ratio'].mean():.2f}
            """)
        else:
            st.info("Нет задач с оценкой и фактическим временем.")

        # Most churned
        st.markdown("---")
        st.markdown("### 🔁 Топ-20 самых «крутящихся» задач")
        st.caption("Задачи с наибольшим количеством смен статуса. Высокий «churn» часто означает проблемы с требованиями, многократные переделки или долгий согласовательный цикл.")
        churn = dft_f.groupby("issue_key").size().reset_index(name="transitions")
        churn = churn.merge(dff[["key", "project_key", "summary", "status", "assignee_name"]],
                            left_on="issue_key", right_on="key", how="left")
        churn = churn.sort_values("transitions", ascending=False).head(20)
        show_cols = ["key", "project_key", "summary", "status", "assignee_name", "transitions"]
        avail = [c for c in show_cols if c in churn.columns]
        st.dataframe(churn[avail], use_container_width=True, hide_index=True)

        # Throughput by Component
        st.markdown("---")
        st.markdown("### 🏷️ Throughput по компонентам")
        st.caption("Количество задач по компонентам (iOS, Android, Windows и т.д.). Показывает, какой продукт самый нагруженный. Задачи с несколькими компонентами учитываются в каждом.")
        comp = dff[dff["components"].notna() & (dff["components"] != "")].copy()
        if len(comp) > 0:
            comp["comp_list"] = comp["components"].str.split("[,;]")
            comp_ex = comp.explode("comp_list")
            comp_ex["comp_list"] = comp_ex["comp_list"].str.strip()
            comp_ex = comp_ex[comp_ex["comp_list"] != ""]
            if len(comp_ex) > 0:
                cc = comp_ex.groupby("comp_list").size().reset_index(name="count").sort_values("count", ascending=True)
                fig = px.bar(cc, x="count", y="comp_list", orientation="h",
                             labels={"count": "Кол-во задач", "comp_list": ""},
                             color="count", color_continuous_scale="Cividis")
                fig.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        # Estimation Accuracy Trend
        st.markdown("---")
        st.markdown("### 📈 Тренд точности оценок")
        st.caption("Средний ratio (факт/оценка) по месяцам. 1.0 = идеальная оценка. >1 = недооцениваем, <1 = переоцениваем. Тренд к 1.0 = учимся оценивать. Только месяцы с ≥3 задачами.")
        est_trend = calc_estimation_trend(dff)
        if len(est_trend) > 0:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=est_trend["ym"], y=est_trend["mean_ratio"],
                                 name="Средний ratio", marker_color="#636EFA", opacity=0.5))
            fig.add_trace(go.Scatter(x=est_trend["ym"], y=est_trend["median_ratio"],
                                     name="Медиана", line=dict(color="#6C5CE7", width=2)))
            fig.add_trace(go.Scatter(x=est_trend["ym"], y=est_trend["mean_ma"],
                                     name="MA3", line=dict(color="#0984E3", width=2)))
            fig.add_hline(y=1.0, line_dash="dash", line_color="red", annotation_text="Идеальная оценка")
            fig.update_layout(height=350, xaxis_title="Месяц закрытия", yaxis_title="Факт/Оценка",
                              legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет данных по тренду оценок.")

        # ---- Time in each individual status ----
        st.markdown("---")
        st.markdown("### ⏱️ Время в каждом статусе")
        st.caption("Медианное время, которое задачи проводят в каждом отдельном статусе (не по категориям To Do / In Progress / Done, а по конкретным статусам: Icebox, Incubator, Clarification, In Review, In review (Design), Draft, Code Review и т.д.). Помогает понять, на каком именно шаге процесса задачи застревают дольше всего — где фактическое бутылочное горлышко. Например, если «In review (Design)» занимает 5 дней, а «In Progress» — 2 дня, то согласование — главная проблема, а не сама работа. Столбцы отсортированы по убыванию медианного времени.")
        time_per_status = calc_time_in_each_status(dff, dft_f)
        if len(time_per_status) > 0:
            fig = px.bar(time_per_status.tail(20), x="median_days", y="status", orientation="h",
                         labels={"median_days": "Медиана, дни", "status": ""},
                         color="median_days", color_continuous_scale="Viridis",
                         hover_data={"mean_days": ":.1f", "count": True})
            fig.update_layout(height=500, showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(time_per_status, use_container_width=True, hide_index=True)
        else:
            st.info("Нет данных о времени по статусам.")

        # ---- Aging WIP (current In-Progress tasks age buckets) ----
        st.markdown("---")
        st.markdown("### 🧊 Aging WIP: возраст текущих задач в работе")
        st.caption("Гистограмма возраста всех задач, которые прямо сейчас находятся в работе (статус In Progress). Возраст считается с момента последней смены статуса — то есть сколько дней задача «висит» на текущем шаге без движения. Бакеты: 1–7 дней (норма), 8–30 (внимание), 31–90 (проблема), 90+ (zombie WIP — формально в работе, фактически мёртв). Много задач 90+ = нужно решить: закрыть, отложить или реально доделать. Zombie WIP засоряет доску и искажает метрики.")
        aging = calc_aging_wip(dff, dft_f)
        if len(aging) > 0:
            col_age1, col_age2, col_age3, col_age4 = st.columns(4)
            col_age1.metric("Всего в работе", len(aging))
            col_age2.metric("8–30 дней", (aging["age_days"].between(8, 30)).sum())
            col_age3.metric("31–90 дней", (aging["age_days"].between(31, 90)).sum())
            col_age4.metric("90+ дней (zombie)", (aging["age_days"] > 90).sum())

            fig = go.Figure()
            fig.add_trace(go.Histogram(x=aging["age_days"], nbinsx=40,
                                       marker_color="#FF6B6B", opacity=0.7,
                                       name="Задач"))
            fig.add_vline(x=7, line_dash="dash", line_color="green", annotation_text="7д")
            fig.add_vline(x=30, line_dash="dash", line_color="orange", annotation_text="30д")
            fig.add_vline(x=90, line_dash="dash", line_color="red", annotation_text="90д")
            fig.update_layout(height=350, xaxis_title="Дней с последней смены статуса",
                              yaxis_title="Кол-во задач")
            st.plotly_chart(fig, use_container_width=True)

            show_cols = ["key", "project_key", "summary", "status", "assignee_name", "age_days"]
            avail = [c for c in show_cols if c in aging.columns]
            st.dataframe(aging[avail].sort_values("age_days", ascending=False).head(20),
                         use_container_width=True, hide_index=True)
        else:
            st.info("Нет задач в работе.")

        # ---- Handoff Count ----
        st.markdown("---")
        st.markdown("### 🔀 Handoff Count: передачи задач между исполнителями")
        st.caption("Сколько раз задача меняла исполнителя от создания до закрытия. 0 смен = один человек довёл от начала до конца. 1–2 = нормально (ушёл в отпуск, передали). 5+ = «горячая картошка» — задача кочует между людьми, каждый раз теряется контекст, увеличивается время на коммуникацию. Часто признаки: плохие требования, которые уточняются у каждого нового исполнителя, или задача, которую никто не хочет доводить. В таблице — топ-20 задач с наибольшим числом передач.")
        handoffs = calc_handoff_count(dff, dfc)
        if len(handoffs) > 0:
            col_h1, col_h2, col_h3 = st.columns(3)
            col_h1.metric("Задач с передачами", len(handoffs))
            col_h2.metric("Медиана передач", f"{handoffs['handoffs'].median():.0f}")
            col_h3.metric("Максимум передач", handoffs["handoffs"].max())

            # Distribution histogram
            fig = go.Figure()
            fig.add_trace(go.Histogram(x=handoffs["handoffs"], nbinsx=20,
                                       marker_color="#636EFA", opacity=0.7, name="Задач"))
            fig.update_layout(height=300, xaxis_title="Кол-во смен исполнителя",
                              yaxis_title="Кол-во задач")
            st.plotly_chart(fig, use_container_width=True)

            show_cols = ["key", "project_key", "summary", "status", "assignee_name", "handoffs"]
            avail = [c for c in show_cols if c in handoffs.columns]
            st.dataframe(handoffs[avail].head(20), use_container_width=True, hide_index=True)
        else:
            st.info("Нет данных о передачах задач.")

        # ---- Workload Balance (Gini) ----
        st.markdown("---")
        st.markdown("### ⚖️ Workload Balance (баланс нагрузки)")
        st.caption("Насколько равномерно задачи распределены между исполнителями. Коэффициент Джини: 0 = идеальное равенство (у всех поровну), 1 = всё на одном человеке. Считается по активным задачам (assigned, не Done) на каждого. Gini < 0.3 = хорошая балансировка, 0.3–0.5 = умеренный перекос, > 0.5 = кто-то перегружен. Полезно смотреть в динамике: если Gini растёт — нагрузка концентрируется, чей-то бэклог переполняется. Гистограмма показывает сколько задач у каждого исполнителя.")
        assigned = dff[dff["assignee_name"].notna() & (dff["status_category"] != "Done")].copy()
        if len(assigned) > 0:
            per_person = assigned["assignee_name"].value_counts()
            gini = calc_gini(per_person.values)
            col_g1, col_g2, col_g3 = st.columns(3)
            col_g1.metric("Активных исполнителей", len(per_person))
            col_g2.metric("Активных задач", len(assigned))
            gini_emoji = "🟢" if gini < 0.3 else ("🟡" if gini < 0.5 else "🔴")
            col_g3.metric("Коэффициент Джини", f"{gini:.2f} {gini_emoji}")

            fig = go.Figure()
            fig.add_trace(go.Bar(x=per_person.values, y=per_person.index, orientation="h",
                                 marker_color="#00CC96", opacity=0.7, name="Задач"))
            fig.update_layout(height=400, xaxis_title="Активные задачи (не Done)",
                              yaxis_title="", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет активных задач с исполнителями.")

        # ---- Priority vs Cycle Time ----
        st.markdown("---")
        st.markdown("### 🔥 Priority vs Cycle Time (приоритет и время)")
        st.caption("Сравнивает медианный cycle time (от создания до закрытия) по уровням приоритета: P1 Critical, P2 High, P3 Medium, P4 Low, P5 Lowest. Если приоритизация работает, P1 закрываются быстрее P4. Если cycle time одинаковый для всех приоритетов — приоритизация НЕ работает: критические задачи ждут в той же очереди, что и низкоприоритетные. P90 показывает «худший случай» — как долго может тянуться задача каждого приоритета.")
        pct = calc_priority_vs_cycle_time(dff)
        if len(pct) > 0:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=pct["priority"], y=pct["median_cycle"], name="Медиана",
                                 marker_color="#636EFA", opacity=0.7))
            fig.add_trace(go.Bar(x=pct["priority"], y=pct["p90_cycle"], name="P90",
                                 marker_color="#EF553B", opacity=0.5))
            fig.update_layout(barmode="group", height=350, xaxis_title="Приоритет",
                              yaxis_title="Дни", legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(pct, use_container_width=True, hide_index=True)
        else:
            st.info("Нет данных по приоритетам.")

        # ---- Project Comparison ----
        st.markdown("---")
        st.markdown("### 📁 Project Comparison (сравнение проектов)")
        st.caption("Медианный cycle time и количество закрытых задач по проектам (AdGuard, AGDNS, AdGuard for Windows, и т.д.). Помогает сравнить, какой проект самый «быстрый», а какой — самый медленный. Важно: cycle time зависит от сложности задач проекта — быстрый проект не значит «лучший», он может просто иметь более простые задачи. Полезно для обсуждения с продакт-менеджерами: где задачи закрываются дольше и почему. Колонка total_count показывает все задачи включая незакрытые.")
        pc = calc_project_comparison(dff)
        if len(pc) > 0:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=pc["project_key"], y=pc["median_cycle"], name="Медиана cycle time",
                                 marker_color="#AB63FA", opacity=0.7))
            fig.add_trace(go.Scatter(x=pc["project_key"], y=pc["p90_cycle"], name="P90",
                                     mode="markers", marker=dict(size=10, color="#EF553B")))
            fig.update_layout(height=350, xaxis_title="Проект", yaxis_title="Дни",
                              legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(pc, use_container_width=True, hide_index=True)
        else:
            st.info("Нет данных по проектам.")

        # ---- Component Cycle Time ----
        st.markdown("---")
        st.markdown("### 🏷️ Cycle Time по компонентам")
        st.caption("Медианный cycle time по продуктовым компонентам (iOS: AdGuard, Android: AdGuard, Windows: AdGuard, Browser: AdGuard и т.д.). Компоненты с большим cycle time — кандидаты на анализ: возможно, там сложнее workflow, больше согласующих, или более объёмные задачи. Задачи с несколькими компонентами учитываются в каждом. Порог: только компоненты с 5+ задачами, чтобы исключить шум.")
        cct = calc_component_cycle_time(dff)
        if len(cct) > 0:
            fig = px.bar(cct.tail(15), x="median_cycle", y="comp_list", orientation="h",
                         labels={"median_cycle": "Медиана, дни", "comp_list": ""},
                         color="median_cycle", color_continuous_scale="Turbo",
                         hover_data={"mean_cycle": ":.1f", "count": True})
            fig.update_layout(height=450, showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(cct, use_container_width=True, hide_index=True)
        else:
            st.info("Нет данных по компонентам.")

        # ---- QoQ Summary ----
        st.markdown("---")
        st.markdown("### 📊 Quarter-over-Quarter: динамика ключевых метрик")
        st.caption("Сравнение ключевых метрик по кварталам: throughput (закрыто), медианный cycle time, rework rate. Колонки Δ показывают изменение по сравнению с предыдущим кварталом: зелёное = улучшение, красное = ухудшение. Throughput: Δ > 0 = выросло (хорошо). Cycle time: Δ < 0 = ускорились (хорошо). Rework: Δ < 0 = качество лучше (хорошо). Быстрый ответ на вопрос «стало лучше или хуже?» без анализа помесячных данных.")
        qoq = calc_qoq_summary(dff, dft_f, smap)
        if len(qoq) > 0:
            qoq_show = qoq[qoq["quarter"] >= "2020Q1"].copy()
            fig = go.Figure()
            fig.add_trace(go.Bar(x=qoq_show["quarter"], y=qoq_show["resolved_count"],
                                 name="Закрыто", marker_color="#636EFA", opacity=0.7,
                                 yaxis="y"))
            fig.add_trace(go.Scatter(x=qoq_show["quarter"], y=qoq_show["median_cycle"],
                                     name="Медиана cycle time (дни)", mode="lines+markers",
                                     line=dict(color="#EF553B", width=2), yaxis="y2"))
            fig.update_layout(height=400, xaxis_title="Квартал",
                              yaxis=dict(title="Закрыто задач"),
                              yaxis2=dict(title="Медиана, дни", overlaying="y", side="right"),
                              legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, use_container_width=True)

            # Delta table with color coding
            delta_df = qoq_show[["quarter", "resolved_count", "resolved_delta",
                                 "median_cycle", "cycle_delta",
                                 "rework_pct", "rework_delta"]].copy()
            delta_df["resolved_delta"] = delta_df["resolved_delta"].round(1)
            delta_df["cycle_delta"] = delta_df["cycle_delta"].round(1)
            delta_df["rework_delta"] = delta_df["rework_delta"].round(1)
            st.dataframe(delta_df, use_container_width=True, hide_index=True)
        else:
            st.info("Нет данных для QoQ сравнения.")

    # ===================== TAB 5: DATA EXPLORER =====================
    with tab5:
        st.markdown("## 🔍 Data Explorer")
        st.caption("Сырые данные по задачам с поиском. Используйте фильтры в сайдбаре для сужения выборки, затем ищите по ключу (например, AG-12345) или по тексту summary.")
        st.markdown(f"Всего задач в выборке: **{len(dff)}**")

        search = st.text_input("🔍 Поиск по key или summary:")
        show_cols = ["key", "project_key", "summary", "status", "assignee_name",
                      "created", "resolution_date", "priority"]
        avail = [c for c in show_cols if c in dff.columns]
        display = dff[avail].copy()
        if search:
            mask_s = display["key"].str.contains(search, case=False, na=False)
            if "summary" in display.columns:
                mask_s |= display["summary"].str.contains(search, case=False, na=False)
            display = display[mask_s]

        st.dataframe(display, use_container_width=True, hide_index=True, height=500)

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button("📥 Скачать issues (CSV)", display.to_csv(index=False).encode("utf-8"),
                               "design_issues_filtered.csv", "text/csv")
        with col_dl2:
            st.download_button("📥 Скачать transitions (CSV)",
                               dft_f.to_csv(index=False).encode("utf-8"),
                               "status_transitions_filtered.csv", "text/csv")


if __name__ == "__main__":
    main()
