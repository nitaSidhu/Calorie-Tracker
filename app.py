"""
Personal weight-loss tracker (single user, local-first).

Install:  pip install streamlit pandas altair pillow pyzbar
Run:      streamlit run app.py
"""

import random
from datetime import date, timedelta

import altair as alt
import pandas as pd
import requests
import streamlit as st
from PIL import Image, ImageOps

try:
    from pyzbar.pyzbar import decode as zbar_decode
except Exception:  # pyzbar missing or the zbar system library isn't installed
    zbar_decode = None

st.set_page_config(page_title="Weight Loss Tracker", page_icon="🥗", layout="centered")
st.markdown("""<style>
.block-container{max-width:720px;padding-top:2rem}
.card{background:#fff;color:#1f2933;border-radius:22px;padding:20px;box-shadow:0 2px 14px rgba(0,0,0,.08);margin-bottom:14px}
.ring-row{display:flex;align-items:center;justify-content:space-around;text-align:center}
.ring-wrap{position:relative;width:150px;height:150px}
.ring-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.big{font-size:1.8rem;font-weight:700;line-height:1.1}
.sub{color:#7b8794;font-size:.8rem}
.mrow{margin-top:12px}
.mhead{display:flex;justify-content:space-between;font-size:.85rem;margin-bottom:4px}
.track{height:8px;background:#eceff1;border-radius:6px;overflow:hidden}
.fill{height:100%;border-radius:6px}
.micon{font-size:1.9rem;text-align:center}
div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:20px}
</style>""", unsafe_allow_html=True)

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


def empty_log() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="object"),
            "meal": pd.Series(dtype="object"),
            "name": pd.Series(dtype="object"),
            **{k: pd.Series(dtype="float64") for k in METRICS},
        }
    )


if "log" not in st.session_state:
    st.session_state.log = empty_log()
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


FDC_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"


def fdc_key() -> str:
    """Use your own free key from Streamlit Secrets (FDC_API_KEY); fall back to the shared demo key."""
    try:
        return st.secrets.get("FDC_API_KEY", "DEMO_KEY")
    except Exception:
        return "DEMO_KEY"


@st.cache_data(ttl=3600, show_spinner="Searching foods...")
def search_foods(query: str, api_key: str) -> list[dict]:
    """Search USDA FoodData Central. Nutrient values come back per 100 g."""
    resp = requests.get(
        FDC_URL, params={"query": query, "pageSize": 15, "api_key": api_key}, timeout=10
    )
    resp.raise_for_status()
    results = []
    for f in resp.json().get("foods", []):
        n = {x["nutrientId"]: (x.get("value") or 0) for x in f.get("foodNutrients", []) if "nutrientId" in x}
        kcal = next((n[i] for i in (1008, 2047, 2048) if i in n), 0)  # energy has a few ids
        desc = f.get("description", "Unknown food")
        if desc.isupper():
            desc = desc.title()
        brand = f.get("brandName") or f.get("brandOwner") or ""
        unit = str(f.get("servingSizeUnit", "")).lower()
        serving = f.get("servingSize") if unit in ("g", "grm", "ml", "mlt") else None
        results.append(
            {
                "id": f.get("fdcId"),
                "name": desc,
                "label": f"{desc} ({brand.title()})" if brand else desc,
                "serving_g": round(float(serving), 1) if serving else 100.0,
                "calories": kcal,
                "protein": n.get(1003, 0),
                "fiber": n.get(1079, 0),
                "sugar": n.get(1235, 0),  # added sugars (0 if the database doesn't list it)
                "sodium": n.get(1093, 0),
            }
        )
    return results


FORM_FIELDS = {"m_name": "", "m_cal": 0.0, "m_pro": 0.0, "m_fib": 0.0, "m_sug": 0.0, "m_sod": 0.0}


def fill_form(food: dict, factor: float):
    """Copy a searched food's nutrition (scaled to the grams eaten) into the entry fields."""
    ss = st.session_state
    ss.m_name = food["name"]
    ss.m_cal = round(food["calories"] * factor, 1)
    ss.m_pro = round(food["protein"] * factor, 1)
    ss.m_fib = round(food["fiber"] * factor, 1)
    ss.m_sug = round(food["sugar"] * factor, 1)
    ss.m_sod = round(food["sodium"] * factor, 1)


def add_from_form():
    """Save the entry fields to the log, then clear them."""
    ss = st.session_state
    name = ss.get("m_name", "").strip()
    if not name:
        ss.form_msg = ("error", "Please enter a food name.")
        return
    vals = [ss.get(k) or 0.0 for k in ("m_cal", "m_pro", "m_fib", "m_sug", "m_sod")]
    add_entry(ss.get("manual_meal", MEALS[0]), name, *vals)
    ss.added_ok = True
    if not any(vals):
        ss.form_msg = ("warning", f"Added {name}, but every nutrition value is 0. Edit it in the Food log if that's wrong.")
    else:
        ss.form_msg = ("success", f"Added {name}")
    for k, v in FORM_FIELDS.items():
        ss[k] = v


def add_entry(meal, name, calories, protein, fiber, sugar, sodium):
    new = pd.DataFrame(
        [[st.session_state.get("log_date", date.today()), meal, name, calories, protein, fiber, sugar, sodium]], columns=COLS
    )
    log = st.session_state.log
    st.session_state.log = new if log.empty else pd.concat([log, new], ignore_index=True)


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
    if st.button("Load demo data"):
        st.session_state.log = make_mock_data()
        st.rerun()
    if st.button("Clear all data"):
        st.session_state.log = empty_log()
        st.rerun()
    st.caption("Data lives in this browser session only. Refreshing the page resets it.")

st.title("🥗 Weight Loss Dashboard")
tab_today, tab_add, tab_dash = st.tabs(["🏠 Home", "📷 Scan barcode", "📊 Analytics"])

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
with tab_dash:
    weekly = weekly_summary(st.session_state.log)
    if weekly.isna().all().all():
        st.info("No data yet. Log some food on the Add food tab and your weekly trends will appear here.")
    else:
        choice = st.radio(
            "Metric",
            list(METRICS),
            format_func=lambda k: METRICS[k]["label"],
            horizontal=True,
        )
        m = METRICS[choice]

        chart_df = weekly[[choice]].rename(columns={choice: "avg"}).reset_index(names="Week")
        chart_df = chart_df.dropna(subset=["avg"]).reset_index(drop=True)
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
    scan_col = st.container()

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

# ---------------------------------------------------------------------------
# Home: app-style daily view
# ---------------------------------------------------------------------------
MEAL_ICON = {"Breakfast": "☕", "Lunch": "🥪", "Dinner": "🥗", "Snack": "🍎"}
MEAL_SPLIT = {"Breakfast": 0.30, "Lunch": 0.35, "Dinner": 0.25, "Snack": 0.10}
BAR_COLOR = {"protein": "#8b5cf6", "fiber": "#f5b301", "sugar": "#f472b6", "sodium": "#38bdf8"}


@st.dialog("Add food")
def food_dialog():
    if st.session_state.pop("added_ok", False):
        st.rerun()  # closes the pop-up and refreshes the home screen
    st.subheader("🔎 Search for a food")
    query = st.text_input(
        "Type a food and press Enter",
        key="food_query",
        placeholder="e.g. banana, Greek yogurt, cuban sandwich",
    )
    results = []
    if query.strip():
        try:
            results = search_foods(query.strip(), fdc_key())
        except Exception:
            st.warning("Food search isn't available right now (connection or rate limit). You can still type values in below.")
        else:
            if not results:
                st.caption("No matches. Try a simpler word, or fill in the form below by hand.")
    if results:
        pick = st.selectbox(
            "Pick a match",
            range(len(results)),
            format_func=lambda i: results[i]["label"],
            key=f"food_pick_{query.strip().lower()}",
        )
        r = results[pick]
        grams = st.number_input(
            "Amount eaten (grams)", min_value=1.0, value=float(r["serving_g"]), step=5.0, key=f"grams_{r['id']}"
        )
        k = grams / 100
        st.caption(
            f"{r['calories'] * k:,.0f} kcal · {r['protein'] * k:,.1f} g protein · {r['fiber'] * k:,.1f} g fiber · "
            f"{r['sugar'] * k:,.1f} g added sugar · {r['sodium'] * k:,.0f} mg sodium"
        )
        st.button("⬇️ Fill the fields below with these values", on_click=fill_form, args=(r, k))
        st.caption("Added sugars show 0 when the database doesn't list them. Check the label on sweet foods.")

    st.divider()
    st.subheader("⌨️ Add to your log")
    st.selectbox("Meal", MEALS, key="manual_meal")
    st.text_input("Food name", key="m_name")
    c1, c2 = st.columns(2)
    c1.number_input("Calories (kcal)", min_value=0.0, step=10.0, key="m_cal")
    c2.number_input("Protein (g)", min_value=0.0, step=1.0, key="m_pro")
    c1.number_input("Fiber (g)", min_value=0.0, step=1.0, key="m_fib")
    c2.number_input("Added sugars (g)", min_value=0.0, step=1.0, key="m_sug")
    c1.number_input("Sodium (mg)", min_value=0.0, step=10.0, key="m_sod")
    st.button("Add to log", type="primary", on_click=add_from_form)
    msg = st.session_state.pop("form_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])



def bar_html(k: str, total: float) -> str:
    cfg = METRICS[k]
    pct = min(total / cfg["target"], 1) * 100 if cfg["target"] else 0
    color = "#ef6b5b" if (cfg["lower_is_better"] and total > cfg["target"]) else BAR_COLOR[k]
    return (
        f'<div class="mrow"><div class="mhead"><span>{cfg["label"]}</span>'
        f'<span><b>{total:,.0f}</b> / {cfg["target"]:,.0f} {cfg["unit"]}</span></div>'
        f'<div class="track"><div class="fill" style="width:{pct:.0f}%;background:{color}"></div></div></div>'
    )


with tab_today:
    day = st.session_state.get("log_date", date.today())
    log = st.session_state.log
    day_df = log[log["date"] == day]

    note = st.session_state.pop("form_msg", None)
    if note:
        st.toast(note[1], icon="✅" if note[0] == "success" else "⚠️")

    st.markdown(f"## {'Today' if day == date.today() else day.strftime('%A, %b %d')}")

    goal = METRICS["calories"]["target"]
    eaten = day_df["calories"].sum()
    remaining = goal - eaten
    over = remaining < 0
    color = "#ef6b5b" if over else "#3dc9a8"
    circ = 2 * 3.14159 * 52
    pct = min(eaten / goal, 1) if goal else 0
    ring = (
        '<svg viewBox="0 0 120 120" width="150" height="150">'
        '<circle cx="60" cy="60" r="52" fill="none" stroke="#eceff1" stroke-width="10"/>'
        f'<circle cx="60" cy="60" r="52" fill="none" stroke="{color}" stroke-width="10" stroke-linecap="round" '
        f'stroke-dasharray="{circ:.1f}" stroke-dashoffset="{circ * (1 - pct):.1f}" transform="rotate(-90 60 60)"/></svg>'
    )
    st.markdown(
        '<div class="card"><div class="ring-row">'
        f'<div><div class="big">{eaten:,.0f}</div><div class="sub">Eaten</div></div>'
        f'<div class="ring-wrap">{ring}<div class="ring-center"><div class="big" style="color:{color}">{abs(remaining):,.0f}</div>'
        f'<div class="sub">{"Over" if over else "Remaining"}</div></div></div>'
        f'<div><div class="big">{goal:,.0f}</div><div class="sub">Goal (kcal)</div></div>'
        "</div></div>",
        unsafe_allow_html=True,
    )

    rows = "".join(bar_html(k, day_df[k].sum()) for k in METRICS if k != "calories")
    st.markdown(f'<div class="card"><b>Nutrition today</b>{rows}</div>', unsafe_allow_html=True)

    for meal_name in MEALS:
        part = day_df[day_df["meal"] == meal_name]
        with st.container(border=True):
            c1, c2, c3 = st.columns([1, 5, 1.3], vertical_alignment="center")
            c1.markdown(f'<div class="micon">{MEAL_ICON[meal_name]}</div>', unsafe_allow_html=True)
            c2.markdown(f"**{meal_name}**  \n{part['calories'].sum():,.0f} / {goal * MEAL_SPLIT[meal_name]:,.0f} kcal")
            if c3.button("➕", key=f"add_{meal_name}", use_container_width=True):
                st.session_state.manual_meal = meal_name
                food_dialog()
            for _, item in part.iterrows():
                st.caption(f"{item['name']} · {item['calories']:,.0f} kcal · {item['protein']:,.0f} g protein")

    with st.expander("✏️ Edit or delete entries"):
        if day_df.empty:
            st.info("Nothing logged for this day yet. Tap ➕ on a meal to log food.")
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


    with st.expander("📈 Last 14 days"):
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
            x=alt.X("date:O", timeUnit="yearmonthdate", title=None, axis=alt.Axis(format="%b %d", labelAngle=-45)),
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
        if daily.empty:
            st.caption("Nothing logged in the last 14 days yet.")
        else:
            st.altair_chart((bars + rule).properties(height=300), use_container_width=True)
