"""
Personal weight-loss tracker (single user, local-first).

Install:  pip install streamlit pandas altair pillow pyzbar
Run:      streamlit run app.py
"""

import random
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st
from PIL import Image

try:
    from pyzbar.pyzbar import decode as zbar_decode
except Exception:  # pyzbar missing or the zbar system library isn't installed
    zbar_decode = None

st.set_page_config(page_title="Weight Loss Tracker", page_icon="🥗", layout="wide")

# ---------------------------------------------------------------------------
# Metric configuration
# ---------------------------------------------------------------------------
METRICS = {
    "calories": {"label": "Calories", "unit": "kcal", "target": 2000, "lower_is_better": True},
    "protein": {"label": "Protein", "unit": "g", "target": 150, "lower_is_better": False},
    "fiber": {"label": "Fiber", "unit": "g", "target": 30, "lower_is_better": False},
    "sugar": {"label": "Added Sugars", "unit": "g", "target": 25, "lower_is_better": True},
    "sodium": {"label": "Sodium", "unit": "mg", "target": 2300, "lower_is_better": True},
}
COLS = ["date", "name", "calories", "protein", "fiber", "sugar", "sodium"]

# ---------------------------------------------------------------------------
# Mock data (4 weeks) with a gentle improving trend
# ---------------------------------------------------------------------------
def make_mock_data() -> pd.DataFrame:
    rng = random.Random(42)
    today = date.today()
    meals = [("Breakfast", 0.25), ("Lunch", 0.35), ("Dinner", 0.30), ("Snacks", 0.10)]
    start = {"calories": 2350, "protein": 105, "fiber": 17, "sugar": 48, "sodium": 3100}
    end = {"calories": 1920, "protein": 148, "fiber": 29, "sugar": 21, "sodium": 2150}
    rows = []
    for days_ago in range(27, -1, -1):
        d = today - timedelta(days=days_ago)
        t = (27 - days_ago) / 27
        for meal, frac in meals:
            row = {"date": d, "name": meal}
            for k in METRICS:
                base = start[k] + (end[k] - start[k]) * t
                noise = rng.uniform(0.92, 1.08)
                row[k] = round(base * frac * noise, 1)
            rows.append(row)
    return pd.DataFrame(rows, columns=COLS)


if "log" not in st.session_state:
    st.session_state.log = make_mock_data()
if "scanned" not in st.session_state:
    st.session_state.scanned = None

# ---------------------------------------------------------------------------
# Barcode helpers
# ---------------------------------------------------------------------------
MOCK_PRODUCTS = {
    "049000028911": {"name": "Coca-Cola Can (12 oz)", "calories": 140, "protein": 0, "fiber": 0, "sugar": 39, "sodium": 45},
    "722252601025": {"name": "Protein Bar", "calories": 200, "protein": 20, "fiber": 9, "sugar": 1, "sodium": 190},
    "016000275287": {"name": "Cheerios (1 cup)", "calories": 100, "protein": 3, "fiber": 3, "sugar": 1, "sodium": 160},
}


def lookup_barcode(barcode: str):
    """PLACEHOLDER for an API lookup.

    Replace with a real call, e.g. Open Food Facts:
        r = requests.get(f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json")
        n = r.json()["product"]["nutriments"]
        calories = n.get("energy-kcal_serving"), protein = n.get("proteins_serving"), ...
    For now it returns a known mock product, or a simulated one for unknown codes.
    """
    if barcode in MOCK_PRODUCTS:
        return MOCK_PRODUCTS[barcode]
    seed = random.Random(barcode)
    return {
        "name": f"Scanned item {barcode[-4:]} (simulated)",
        "calories": seed.randint(80, 400),
        "protein": seed.randint(0, 25),
        "fiber": seed.randint(0, 8),
        "sugar": seed.randint(0, 20),
        "sodium": seed.randint(20, 600),
    }


def decode_barcodes(img: Image.Image) -> list[str]:
    if zbar_decode is None:
        return []
    return [b.data.decode("utf-8") for b in zbar_decode(img)]


def add_entry(name, calories, protein, fiber, sugar, sodium):
    new = pd.DataFrame(
        [[date.today(), name, calories, protein, fiber, sugar, sodium]], columns=COLS
    )
    st.session_state.log = pd.concat([st.session_state.log, new], ignore_index=True)


# ---------------------------------------------------------------------------
# Weekly aggregation (rolling 4 weeks, Week 4 = the most recent 7 days)
# ---------------------------------------------------------------------------
def weekly_summary(log: pd.DataFrame) -> pd.DataFrame:
    df = log.copy()
    df["date"] = pd.to_datetime(df["date"])
    daily = df.groupby("date")[list(METRICS)].sum().reset_index()
    days_ago = (pd.Timestamp(date.today()) - daily["date"]).dt.days
    daily = daily[days_ago < 28].copy()
    daily["week_num"] = 4 - (days_ago[days_ago < 28] // 7)
    weekly = daily.groupby("week_num")[list(METRICS)].mean().reindex([1, 2, 3, 4])
    weekly.index = [f"Week {i}" for i in weekly.index]
    return weekly


# ---------------------------------------------------------------------------
# Sidebar: editable targets
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("🎯 Daily targets")
    for k, m in METRICS.items():
        m["target"] = st.number_input(
            f"{m['label']} ({m['unit']})", min_value=0, value=int(m["target"]), step=5, key=f"t_{k}"
        )
    st.divider()
    if st.button("Reset to mock data"):
        st.session_state.log = make_mock_data()
        st.rerun()
    st.caption("Data lives in this browser session only. Refreshing the page resets it.")

st.title("🥗 Weight Loss Dashboard")
tab_dash, tab_add, tab_log = st.tabs(["📊 Dashboard", "➕ Add food", "📋 Today's log"])

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
with tab_dash:
    weekly = weekly_summary(st.session_state.log)
    choice = st.radio(
        "Metric",
        list(METRICS),
        format_func=lambda k: METRICS[k]["label"],
        horizontal=True,
    )
    m = METRICS[choice]

    chart_df = weekly[[choice]].rename(columns={choice: "avg"}).reset_index(names="Week")
    chart_df["change"] = chart_df["avg"].diff()
    chart_df["label"] = chart_df["change"].apply(
        lambda v: "" if pd.isna(v) else f"{'▲' if v > 0 else '▼'} {abs(v):.0f}"
    )
    chart_df["status"] = chart_df["avg"].apply(
        lambda v: "On target"
        if ((v <= m["target"]) if m["lower_is_better"] else (v >= m["target"]))
        else "Off target"
    )

    left, right = st.columns([2, 1], gap="large")

    with left:
        st.subheader(f"{m['label']}: 4-week trend")
        base = alt.Chart(chart_df).encode(x=alt.X("Week:N", sort=None, title=None))
        bars = base.mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6, size=70).encode(
            y=alt.Y("avg:Q", title=f"Daily average ({m['unit']})"),
            color=alt.Color(
                "status:N",
                scale=alt.Scale(domain=["On target", "Off target"], range=["#2e9e6b", "#f0a04b"]),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("Week:N"),
                alt.Tooltip("avg:Q", format=".0f", title="Avg"),
                alt.Tooltip("change:Q", format="+.0f", title="Change vs prior week"),
            ],
        )
        variance = base.mark_text(dy=-10, fontSize=14, fontWeight="bold").encode(
            y="avg:Q", text="label:N"
        )
        target_line = (
            alt.Chart(pd.DataFrame({"target": [m["target"]]}))
            .mark_rule(color="red", strokeDash=[8, 5], strokeWidth=2.5)
            .encode(y="target:Q")
        )
        target_text = (
            alt.Chart(pd.DataFrame({"target": [m["target"]], "t": [f"Target {m['target']} {m['unit']}"]}))
            .mark_text(align="left", dx=4, dy=-8, color="red", fontSize=12)
            .encode(y="target:Q", text="t:N", x=alt.value(0))
        )
        st.altair_chart(
            (bars + variance + target_line + target_text).properties(height=380),
            use_container_width=True,
        )
        st.caption("▲/▼ above each bar = intake change vs the previous week. Red dashed line = your target.")

    with right:
        st.subheader("This week vs goal")
        current, previous = weekly.iloc[3], weekly.iloc[2]
        for k, cfg in METRICS.items():
            avg = current[k]
            if pd.isna(avg):
                continue
            gap = avg - cfg["target"]
            wow = avg - previous[k] if not pd.isna(previous[k]) else 0
            word = "below" if gap < 0 else "above"
            st.metric(
                label=f"{cfg['label']} (daily avg)",
                value=f"{avg:,.0f} {cfg['unit']}",
                delta=f"{gap:+,.0f} {cfg['unit']} {word} target",
                delta_color="inverse" if cfg["lower_is_better"] else "normal",
                help=f"Week-over-week change: {wow:+,.0f} {cfg['unit']}",
            )

    with st.expander("Weekly averages table"):
        st.dataframe(weekly.round(0), use_container_width=True)

# ---------------------------------------------------------------------------
# Add food: barcode + manual
# ---------------------------------------------------------------------------
with tab_add:
    scan_col, manual_col = st.columns(2, gap="large")

    with scan_col:
        st.subheader("📷 Scan a barcode")
        if zbar_decode is None:
            st.warning(
                "pyzbar isn't available. Install it plus the zbar system library "
                "(see the notes at the top of this file)."
            )
        photo = st.camera_input("Hold the barcode steady and take a photo")
        if photo is not None:
            codes = decode_barcodes(Image.open(photo))
            if codes:
                st.session_state.scanned = {"barcode": codes[0], "product": lookup_barcode(codes[0])}
            else:
                st.error("No barcode detected. Try better lighting or move closer.")

        sc = st.session_state.scanned
        if sc:
            p = sc["product"]
            st.success(f"Found barcode {sc['barcode']}: {p['name']}")
            with st.form(f"scan_form_{sc['barcode']}"):
                servings = st.number_input("Servings", min_value=0.25, value=1.0, step=0.25)
                st.write(
                    f"Per serving: {p['calories']} kcal · {p['protein']}g protein · "
                    f"{p['fiber']}g fiber · {p['sugar']}g sugar · {p['sodium']}mg sodium"
                )
                if st.form_submit_button("Add to log"):
                    add_entry(
                        p["name"],
                        p["calories"] * servings,
                        p["protein"] * servings,
                        p["fiber"] * servings,
                        p["sugar"] * servings,
                        p["sodium"] * servings,
                    )
                    st.session_state.scanned = None
                    st.success("Added!")

    with manual_col:
        st.subheader("⌨️ Manual entry")
        with st.form("manual_form", clear_on_submit=True):
            name = st.text_input("Food name")
            c1, c2 = st.columns(2)
            cal = c1.number_input("Calories (kcal)", min_value=0.0, step=10.0)
            pro = c2.number_input("Protein (g)", min_value=0.0, step=1.0)
            fib = c1.number_input("Fiber (g)", min_value=0.0, step=1.0)
            sug = c2.number_input("Added sugars (g)", min_value=0.0, step=1.0)
            sod = c1.number_input("Sodium (mg)", min_value=0.0, step=10.0)
            if st.form_submit_button("Add to log"):
                if name.strip():
                    add_entry(name.strip(), cal, pro, fib, sug, sod)
                    st.success(f"Added {name.strip()}")
                else:
                    st.error("Please enter a food name.")

# ---------------------------------------------------------------------------
# Today's log
# ---------------------------------------------------------------------------
with tab_log:
    log = st.session_state.log
    today_df = log[log["date"] == date.today()]
    st.subheader("Today's totals")
    cols = st.columns(len(METRICS))
    for col, (k, cfg) in zip(cols, METRICS.items()):
        total = today_df[k].sum()
        col.metric(
            cfg["label"],
            f"{total:,.0f} {cfg['unit']}",
            f"{total - cfg['target']:+,.0f} vs target",
            delta_color="inverse" if cfg["lower_is_better"] else "normal",
        )
    st.dataframe(today_df.drop(columns="date").round(1), use_container_width=True, hide_index=True)
