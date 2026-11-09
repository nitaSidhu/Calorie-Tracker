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
from PIL import Image, ImageOps

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
MEALS = ["Breakfast", "Lunch", "Dinner", "Snack"]
COLS = ["date", "meal", "name", "calories", "protein", "fiber", "sugar", "sodium"]

# ---------------------------------------------------------------------------
# Mock data (4 weeks) with a gentle improving trend
# ---------------------------------------------------------------------------
def make_mock_data() -> pd.DataFrame:
    rng = random.Random(42)
    today = date.today()
    meals = [("Breakfast", 0.25), ("Lunch", 0.35), ("Dinner", 0.30), ("Snack", 0.10)]
    start = {"calories": 2350, "protein": 105, "fiber": 17, "sugar": 48, "sodium": 3100}
    end = {"calories": 1920, "protein": 148, "fiber": 29, "sugar": 21, "sodium": 2150}
    rows = []
    for days_ago in range(27, -1, -1):
        d = today - timedelta(days=days_ago)
        t = (27 - days_ago) / 27
        for meal, frac in meals:
            row = {"date": d, "meal": meal, "name": f"{meal} (sample)"}
            for k in METRICS:
                base = start[k] + (end[k] - start[k]) * t
                noise = rng.uniform(0.92, 1.08)
                row[k] = round(base * frac * noise, 1)
            rows.append(row)
    return pd.DataFrame(rows, columns=COLS)


if "log" not in st.session_state:
    st.session_state.log = make_mock_data()
if "meal" not in st.session_state.log.columns:
    st.session_state.log.insert(1, "meal", "Snack")
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
    """Try several versions of the photo (grayscale, contrast boost, resized, rotated)."""
    if zbar_decode is None:
        return []
    img = ImageOps.exif_transpose(img).convert("L")  # phone photos carry a rotation flag
    w, h = img.size
    longest = max(w, h)
    variants = [img, ImageOps.autocontrast(img)]
    if longest > 1600:  # huge phone photos decode better when shrunk
        k = 1600 / longest
        variants.append(img.resize((int(w * k), int(h * k)), Image.LANCZOS))
    elif longest < 1000:  # small webcam frames decode better when enlarged
        variants.append(img.resize((w * 2, h * 2), Image.LANCZOS))
    for v in variants:
        for angle in (0, 90, 270):  # also catches barcodes held sideways
            candidate = v if angle == 0 else v.rotate(angle, expand=True)
            found = zbar_decode(candidate)
            if found:
                return [b.data.decode("utf-8") for b in found]
    return []


# Dashed "aim here" frame drawn over the webcam preview (visual guide only)
GUIDE_CSS = """
<style>
div[data-testid="stCameraInput"] { position: relative; }
div[data-testid="stCameraInput"]::after {
    content: "Line up barcode here";
    position: absolute; top: 18%; left: 12%; width: 76%; height: 32%;
    border: 3px dashed #ff4b4b; border-radius: 12px;
    color: #ff4b4b; font-size: 13px; font-weight: 600;
    display: flex; align-items: flex-end; justify-content: center; padding-bottom: 4px;
    pointer-events: none; z-index: 10;
}
</style>
"""


def add_entry(meal, name, calories, protein, fiber, sugar, sodium):
    new = pd.DataFrame(
        [[st.session_state.get("log_date", date.today()), meal, name, calories, protein, fiber, sugar, sodium]], columns=COLS
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
    st.header("📅 Logging date")
    st.date_input("Day to view / log", value=date.today(), max_value=date.today(), key="log_date")
    st.divider()
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
tab_today, tab_add, tab_dash = st.tabs(["📅 Daily tracker", "➕ Add food", "📊 Weekly trends"])

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
        method = st.radio(
            "How do you want to scan?",
            ["📱 Photo (best on phone)", "💻 Webcam with guide box", "🔢 Type the number"],
        )
        photo = None
        if method.startswith("📱"):
            photo = st.file_uploader(
                "Take or choose a photo of the barcode", type=["jpg", "jpeg", "png"], key="bc_upload"
            )
            st.caption(
                "On a phone this opens your camera app (with autofocus). Get close, keep the "
                "stripes level, and tap the screen to focus before shooting."
            )
        elif method.startswith("💻"):
            st.markdown(GUIDE_CSS, unsafe_allow_html=True)
            photo = st.camera_input("Fit the barcode inside the red box, then take the photo")
            st.caption("The box is only a visual guide. Fill it with the stripes, level and well lit.")
        else:
            typed = st.text_input("Digits printed under the barcode", key="bc_typed")
            if st.button("Look up"):
                digits = typed.strip().replace(" ", "")
                if digits.isdigit() and 8 <= len(digits) <= 14:
                    st.session_state.scanned = {"barcode": digits, "product": lookup_barcode(digits)}
                else:
                    st.error("Enter the 8 to 14 digits shown under the barcode.")

        if photo is not None:
            data = photo.getvalue()
            photo_hash = hash(data)
            if photo_hash != st.session_state.get("last_photo_hash"):  # only decode each photo once
                st.session_state.last_photo_hash = photo_hash
                codes = decode_barcodes(Image.open(photo))
                if codes:
                    st.session_state.scanned = {"barcode": codes[0], "product": lookup_barcode(codes[0])}
                else:
                    st.session_state.scanned = None
                    st.error("No barcode detected. Move closer, add light, or type the number instead.")

        sc = st.session_state.scanned
        if sc:
            p = sc["product"]
            st.success(f"Found barcode {sc['barcode']}: {p['name']}")
            with st.form(f"scan_form_{sc['barcode']}"):
                meal = st.selectbox("Meal", MEALS, key="scan_meal")
                servings = st.number_input("Servings", min_value=0.25, value=1.0, step=0.25)
                st.write(
                    f"Per serving: {p['calories']} kcal · {p['protein']}g protein · "
                    f"{p['fiber']}g fiber · {p['sugar']}g sugar · {p['sodium']}mg sodium"
                )
                if st.form_submit_button("Add to log"):
                    add_entry(
                        meal,
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
            meal = st.selectbox("Meal", MEALS, key="manual_meal")
            name = st.text_input("Food name")
            c1, c2 = st.columns(2)
            cal = c1.number_input("Calories (kcal)", min_value=0.0, step=10.0)
            pro = c2.number_input("Protein (g)", min_value=0.0, step=1.0)
            fib = c1.number_input("Fiber (g)", min_value=0.0, step=1.0)
            sug = c2.number_input("Added sugars (g)", min_value=0.0, step=1.0)
            sod = c1.number_input("Sodium (mg)", min_value=0.0, step=10.0)
            if st.form_submit_button("Add to log"):
                if name.strip():
                    add_entry(meal, name.strip(), cal, pro, fib, sug, sod)
                    st.success(f"Added {name.strip()}")
                else:
                    st.error("Please enter a food name.")

# ---------------------------------------------------------------------------
# Daily tracker (home screen)
# ---------------------------------------------------------------------------
with tab_today:
    day = st.session_state.get("log_date", date.today())
    title = "Today" if day == date.today() else day.strftime("%A, %b %d")
    st.subheader(f"📅 {title}")

    log = st.session_state.log
    day_df = log[log["date"] == day]

    cols = st.columns(len(METRICS))
    for col, (k, cfg) in zip(cols, METRICS.items()):
        total = day_df[k].sum()
        col.metric(
            cfg["label"],
            f"{total:,.0f} {cfg['unit']}",
            f"{total - cfg['target']:+,.0f} vs target",
            delta_color="inverse" if cfg["lower_is_better"] else "normal",
        )
        col.progress(min(total / cfg["target"], 1.0) if cfg["target"] else 0.0)

    st.markdown("#### By meal")
    meal_cols = st.columns(len(MEALS))
    for mcol, meal_name in zip(meal_cols, MEALS):
        part = day_df[day_df["meal"] == meal_name]
        mcol.metric(
            meal_name,
            f"{part['calories'].sum():,.0f} kcal",
            f"{part['protein'].sum():,.0f} g protein",
            delta_color="off",
        )

    st.markdown("#### Food log")
    if day_df.empty:
        st.info("Nothing logged for this day yet. Use the **Add food** tab to log a meal.")
    else:
        ver = st.session_state.get("editor_ver", 0)
        editor_df = (
            day_df.assign(_o=day_df["meal"].map({m: i for i, m in enumerate(MEALS)}))
            .sort_values("_o", kind="stable")
            .drop(columns=["_o", "date"])
            .round(1)
        )
        editor_df.insert(0, "Delete", False)
        edited = st.data_editor(
            editor_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "meal": st.column_config.SelectboxColumn("Meal", options=MEALS, required=True),
                "name": st.column_config.TextColumn("Food", required=True),
                **{
                    k: st.column_config.NumberColumn(f"{METRICS[k]['label']} ({METRICS[k]['unit']})", min_value=0)
                    for k in METRICS
                },
            },
            key=f"editor_{day}_{ver}",
        )
        st.caption("Click a cell to edit it (Meal is a dropdown). Tick **Delete** to remove a row. Then press Save changes.")
        if st.button("💾 Save changes", type="primary"):
            new = st.session_state.log.copy()
            for idx, row in edited.iterrows():
                if row["Delete"]:
                    new = new.drop(index=idx)
                else:
                    new.at[idx, "meal"] = row["meal"]
                    new.at[idx, "name"] = row["name"]
                    for k in METRICS:
                        new.at[idx, k] = 0 if pd.isna(row[k]) else row[k]
            st.session_state.log = new.reset_index(drop=True)
            st.session_state.editor_ver = ver + 1
            st.rerun()

    st.markdown("#### Last 14 days")
    mk = st.selectbox("Metric", list(METRICS), format_func=lambda k: METRICS[k]["label"], key="daily_metric")
    mc = METRICS[mk]
    d = log.copy()
    d["date"] = pd.to_datetime(d["date"])
    daily = d.groupby("date")[mk].sum().reset_index()
    daily = daily[daily["date"] >= pd.Timestamp(date.today()) - pd.Timedelta(days=13)]
    daily["status"] = daily[mk].apply(
        lambda v: "On target"
        if ((v <= mc["target"]) if mc["lower_is_better"] else (v >= mc["target"]))
        else "Off target"
    )
    bars = alt.Chart(daily).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
        y=alt.Y(f"{mk}:Q", title=f"{mc['label']} ({mc['unit']})"),
        color=alt.Color(
            "status:N",
            scale=alt.Scale(domain=["On target", "Off target"], range=["#2e9e6b", "#f0a04b"]),
            legend=alt.Legend(title=None, orient="bottom"),
        ),
        tooltip=[alt.Tooltip("date:T", format="%b %d"), alt.Tooltip(f"{mk}:Q", format=".0f")],
    )
    rule = (
        alt.Chart(pd.DataFrame({"target": [mc["target"]]}))
        .mark_rule(color="red", strokeDash=[8, 5], strokeWidth=2.5)
        .encode(y="target:Q")
    )
    st.altair_chart((bars + rule).properties(height=300), use_container_width=True)
