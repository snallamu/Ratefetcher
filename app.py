"""Gold Rates – India & Canada, from COMEX and MCX, in 24K and 22K. Run: streamlit run app.py"""
import re
import datetime as dt
import requests
import pandas as pd
import streamlit as st

OZ_G = 31.1035  # grams per troy ounce
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
KARATS = {"24K": 1.0, "22K": 22 / 24}  # purity relative to 24K (MCX/COMEX quote ~999 gold)
SYM = {"INR": "₹", "CAD": "C$", "USD": "$"}

st.set_page_config(page_title="Gold Rates – India & Canada", page_icon="🪙", layout="wide")


@st.cache_data(ttl=60, show_spinner=False)
def yahoo(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
    r.raise_for_status()
    m = r.json()["chart"]["result"][0]["meta"]
    price = m["regularMarketPrice"]
    prev = m.get("chartPreviousClose") or m.get("previousClose")
    return {"price": price, "change": price - prev, "pct": (price - prev) / prev * 100}


@st.cache_data(ttl=60, show_spinner=False)
def mcx(exp: str) -> dict:
    """Best-effort scrape of Moneycontrol MCX gold (INR per 10g). Page may be JS-rendered/blocked."""
    url = f"https://www.moneycontrol.com/commodity/mcx-gold-price/?type=futures&exp={exp}"
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"}, timeout=10)
        r.raise_for_status()
        html = r.text
        num = lambda s: float(s.replace(",", ""))

        def pick(pattern):
            m = re.search(pattern, html)
            return num(m.group(1)) if m else None

        price = pick(r'"(?:lastPrice|LastPrice|ltp|LTP)"\s*:\s*"?([\d,]+\.?\d*)')
        change = pick(r'"(?:priceChange|pricechange|change)"\s*:\s*"?(-?[\d,]+\.?\d*)')
        pct = pick(r'"(?:pricePercentChange|percentChange|pricepercentchange)"\s*:\s*"?(-?[\d,]+\.?\d*)')
        if not (price and 50_000 < price < 500_000):
            m = re.search(r"(?:₹|Rs\.?)?\s*([1-9]\d,\d{2},\d{3}(?:\.\d+)?|\d{6}(?:\.\d+)?)", html)
            price = num(m.group(1)) if m else None
        if not (price and 50_000 < price < 500_000):
            raise ValueError("price not found in page (site may be JS-rendered or blocking)")
        return {"ok": True, "price": price, "change": change, "pct": pct, "url": url}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "url": url}


def money(v, cur):
    return "–" if v is None else f"{SYM[cur]}{v:,.2f}"


def delta(chg, pct, cur):
    if chg is None:
        return None
    pct_txt = f" ({pct:+.2f}%)" if pct is not None else ""
    return f"{'-' if chg < 0 else '+'}{SYM[cur]}{abs(chg):,.2f}{pct_txt}"


def render_source(title, per10g_24k, chg10g, pct, cur, premium, note=None):
    """per10g_24k: price of 10g of 24K gold in `cur`. Shows 24K & 22K metrics + table."""
    st.subheader(title)
    if per10g_24k is None:
        st.warning(note or "Rate unavailable")
        return
    base = per10g_24k * (1 + premium / 100)
    cols = st.columns(len(KARATS))
    rows = []
    for col, (k, f) in zip(cols, KARATS.items()):
        v = base * f
        c = None if chg10g is None else chg10g * f * (1 + premium / 100)
        col.metric(f"{k} · per 10g", money(v, cur), delta(c, pct, cur))
        o = money(((v / 10) * 8), cur)
        rows.append({"Karat": k, "Per gram": money(v / 10, cur),"Per 8g": o, "Per 10g": money(v, cur),
                     "Per oz (31.1g)": money(v / 10 * OZ_G, cur)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    if note:
        st.caption(note)


# ---------------- Sidebar ----------------
st.sidebar.header("Settings")
exp = st.sidebar.date_input("MCX contract expiry", dt.date(2026, 12, 4)).isoformat()
premium_in = st.sidebar.number_input("India add-on % (duty/GST/making)", 0.0, 50.0, 0.0, 0.5)
premium_ca = st.sidebar.number_input("Canada add-on % (premium/tax)", 0.0, 50.0, 0.0, 0.5)
if st.sidebar.button("🔄 Refresh now"):
    st.cache_data.clear()
st.sidebar.caption("Auto data cache: 60 seconds. Rates are benchmark (spot/futures) prices, not retail jeweller prices.")

# ---------------- Data ----------------
st.title("🪙 Gold Rates – India & Canada")
try:
    gold, usdinr, usdcad = yahoo("GC=F"), yahoo("USDINR=X"), yahoo("CAD=X")
except Exception as e:  # noqa: BLE001
    st.error(f"Could not load COMEX/FX data: {e}")
    st.stop()
m = mcx(exp)

# COMEX direction banner
txt = f"COMEX Gold (GC=F): ${gold['price']:,.2f}/oz  |  {gold['change']:+.2f} ({gold['pct']:+.2f}%)"
if gold["change"] > 0:
    st.success("▲ POSITIVE · " + txt)
elif gold["change"] < 0:
    st.error("▼ NEGATIVE · " + txt)
else:
    st.info("■ FLAT · " + txt)
st.caption(f"USD/INR {usdinr['price']:.2f} · USD/CAD {usdcad['price']:.4f} · "
           f"Updated {dt.datetime.now().strftime('%d %b %Y %H:%M:%S')}")

# ---- Conversions ----
inr_to_cad = usdcad["price"] / usdinr["price"]            # 1 INR in CAD
comex_inr_10g = gold["price"] / OZ_G * 10 * usdinr["price"]
comex_inr_chg = gold["change"] / OZ_G * 10 * usdinr["price"]
comex_cad_10g = gold["price"] / OZ_G * 10 * usdcad["price"]
comex_cad_chg = gold["change"] / OZ_G * 10 * usdcad["price"]

mcx_inr = m["price"] if m["ok"] else None
mcx_inr_chg = m.get("change") if m["ok"] else None
mcx_pct = m.get("pct") if m["ok"] else None
mcx_cad = mcx_inr * inr_to_cad if mcx_inr else None
mcx_cad_chg = mcx_inr_chg * inr_to_cad if mcx_inr_chg is not None else None
mcx_note = None if m["ok"] else f"MCX unavailable: {m['error']}"

tab_in, tab_ca, tab_raw = st.tabs(["🇮🇳 India (INR)", "🇨🇦 Canada (CAD)", "Raw / Compare"])

with tab_in:
    c1, c2 = st.columns(2)
    with c1:
        render_source(f"MCX Gold (exp {exp})", mcx_inr, mcx_inr_chg, mcx_pct, "INR", premium_in, mcx_note)
    with c2:
        render_source("COMEX Gold → INR", comex_inr_10g, comex_inr_chg, gold["pct"], "INR", premium_in,
                      "COMEX USD/oz converted at live USD/INR.")

with tab_ca:
    c1, c2 = st.columns(2)
    with c1:
        render_source(f"MCX Gold → CAD (exp {exp})", mcx_cad, mcx_cad_chg, mcx_pct, "CAD", premium_ca,
                      mcx_note or "MCX INR price converted to CAD via live INR→CAD rate.")
    with c2:
        render_source("COMEX Gold → CAD", comex_cad_10g, comex_cad_chg, gold["pct"], "CAD", premium_ca,
                      "COMEX USD/oz converted at live USD/CAD.")

with tab_raw:
    st.write("**24K price per 10g, all four combinations (before add-ons)**")
    st.dataframe(pd.DataFrame([
        {"Location": "India", "Source": "MCX", "Currency": "INR", "24K /10g": mcx_inr, "22K /10g": mcx_inr and mcx_inr * 22 / 24},
        {"Location": "India", "Source": "COMEX", "Currency": "INR", "24K /10g": comex_inr_10g, "22K /10g": comex_inr_10g * 22 / 24},
        {"Location": "Canada", "Source": "MCX", "Currency": "CAD", "24K /10g": mcx_cad, "22K /10g": mcx_cad and mcx_cad * 22 / 24},
        {"Location": "Canada", "Source": "COMEX", "Currency": "CAD", "24K /10g": comex_cad_10g, "22K /10g": comex_cad_10g * 22 / 24},
    ]).round(2), hide_index=True, use_container_width=True)
    if mcx_inr:
        spread = mcx_inr - comex_inr_10g
        st.metric("MCX premium over COMEX-implied (INR/10g)", money(spread, "INR"),
                  f"{spread / comex_inr_10g * 100:+.2f}%")
    st.caption(f"Source page: {m['url']}")
