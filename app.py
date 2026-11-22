"""India Gold Rates – MCX & COMEX, 24K and 22K. Run: streamlit run app.py"""
import re
import datetime as dt
import requests
import pandas as pd
import streamlit as st

OZ_G = 31.1035  # grams per troy ounce
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
KARATS = {"24K": 1.0, "22K": 22 / 24}

st.set_page_config(page_title="India Gold Rates", page_icon="🪙", layout="wide")


def http_get(url: str, **kw):
    """Chrome-impersonating GET (bypasses Akamai-style 403s); falls back to plain requests."""
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, impersonate="chrome124", timeout=15,
                     headers={"Accept-Language": "en-IN,en;q=0.9"}, **kw)
    except ImportError:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"}, timeout=15, **kw)
    r.raise_for_status()
    return r


@st.cache_data(ttl=60, show_spinner=False)
def yahoo(symbol: str) -> dict:
    """Latest price + change vs the PREVIOUS DAILY close (not the 5-day-ago close)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    res = requests.get(url, headers={"User-Agent": UA}, timeout=10)
    res.raise_for_status()
    result = res.json()["chart"]["result"][0]
    price = result["meta"]["regularMarketPrice"]
    closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    prev = closes[-2] if len(closes) >= 2 else result["meta"].get("chartPreviousClose", price)
    return {"price": price, "change": price - prev, "pct": (price - prev) / prev * 100}


def _mcx_moneycontrol(exp: str) -> dict:
    url = f"https://www.moneycontrol.com/commodity/mcx-gold-price/?type=futures&exp={exp}"
    html = http_get(url).text
    num = lambda s: float(s.replace(",", ""))

    def pick(p):
        m = re.search(p, html)
        return num(m.group(1)) if m else None

    price = pick(r'"(?:lastPrice|LastPrice|ltp|LTP)"\s*:\s*"?([\d,]+\.?\d*)')
    change = pick(r'"(?:priceChange|pricechange|change)"\s*:\s*"?(-?[\d,]+\.?\d*)')
    pct = pick(r'"(?:pricePercentChange|percentChange|pricepercentchange)"\s*:\s*"?(-?[\d,]+\.?\d*)')
    if not (price and 50_000 < price < 500_000):
        m = re.search(r"(?:₹|Rs\.?)?\s*([1-9]\d,\d{2},\d{3}(?:\.\d+)?|\d{6}(?:\.\d+)?)", html)
        price = num(m.group(1)) if m else None
    if not (price and 50_000 < price < 500_000):
        raise ValueError("price not found in page (likely JS-rendered)")
    return {"price": price, "change": change, "pct": pct, "label": f"MCX Gold Futures (exp {exp})", "src": "Moneycontrol"}


def _mcx_spot() -> dict:
    from mcxdata import mcx  # uses curl_cffi against mcxindia.com
    df = mcx.get_spot_recent(commodity="GOLD")
    if df is None or df.empty:
        raise ValueError("empty MCX spot response")
    price_col = next(c for c in df.columns if "Spot Price" in c)
    row = df.iloc[0]
    price = float(str(row[price_col]).replace(",", ""))
    chg = None
    if "Up/Down" in df.columns:
        try:
            chg = float(str(row["Up/Down"]).replace(",", ""))
        except ValueError:
            pass
    return {"price": price, "change": chg, "pct": (chg / (price - chg) * 100) if chg else None,
            "label": "MCX Gold Spot (per 10g)", "src": "mcxindia.com"}


@st.cache_data(ttl=60, show_spinner=False)
def mcx_rate(exp: str) -> dict:
    errors = []
    for fn, args in ((_mcx_moneycontrol, (exp,)), (_mcx_spot, ())):
        try:
            return {"ok": True, **fn(*args)}
        except Exception as e:  # noqa: BLE001
            errors.append(f"{fn.__name__}: {e}")
    return {"ok": False, "errors": errors}


def inr(v):
    return "–" if v is None else f"₹{v:,.2f}"


def delta(chg, pct):
    if chg is None:
        return None
    return f"{'-' if chg < 0 else '+'}₹{abs(chg):,.2f}" + (f" ({pct:+.2f}%)" if pct is not None else "")


def render(title, caption, p24, chg, pct, premium):
    st.subheader(title)
    if p24 is None:
        return
    cols, rows = st.columns(2), []
    for col, (k, f) in zip(cols, KARATS.items()):
        mult = f * (1 + premium / 100)
        col.metric(f"{k} · per 10g", inr(p24 * mult), delta(None if chg is None else chg * mult, pct))
        rows.append({"Karat": k, "Per gram": inr(p24 * mult / 10), "Per 10g": inr(p24 * mult),
                     "Per 100g": inr(p24 * mult * 10)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption(caption)


# ---------------- Sidebar ----------------
st.sidebar.header("Settings")
exp = st.sidebar.date_input("MCX contract expiry", dt.date(2026, 12, 4)).isoformat()
premium = st.sidebar.number_input("Add-on % (import duty / GST / making)", 0.0, 50.0, 0.0, 0.5)
if st.sidebar.button("🔄 Refresh now"):
    st.cache_data.clear()
st.sidebar.caption("Cached 60s. Benchmark prices, not jeweller retail rates.")

# ---------------- Data ----------------
st.title("🪙 India Gold Rates")
try:
    gold, usdinr = yahoo("GC=F"), yahoo("USDINR=X")
except Exception as e:  # noqa: BLE001
    st.error(f"Could not load COMEX/USDINR data: {e}")
    st.stop()

banner = (f"COMEX Gold (GC=F): ${gold['price']:,.2f}/oz | {gold['change']:+.2f} ({gold['pct']:+.2f}%) vs previous close")
(st.success if gold["change"] > 0 else st.error if gold["change"] < 0 else st.info)(
    ("▲ POSITIVE · " if gold["change"] > 0 else "▼ NEGATIVE · " if gold["change"] < 0 else "■ FLAT · ") + banner)
st.caption(f"USD/INR {usdinr['price']:.2f} · Updated {dt.datetime.now():%d %b %Y %H:%M:%S}")

k = 10 / OZ_G * usdinr["price"]  # USD/oz -> INR per 10g
comex_10g, comex_chg = gold["price"] * k, gold["change"] * k

m = mcx_rate(exp)
c1, c2 = st.columns(2)
with c1:
    if m["ok"]:
        render(m["label"], f"Source: {m['src']}", m["price"], m["change"], m["pct"], premium)
    else:
        st.subheader("MCX Gold")
        st.warning("MCX rate unavailable from all sources.")
        with st.expander("Details"):
            st.write("\n".join(m["errors"]))
with c2:
    render("COMEX Gold → INR", "COMEX USD/oz × live USD/INR ÷ 31.1035 × 10.", comex_10g, comex_chg, gold["pct"], premium)

if m["ok"]:
    spread = m["price"] - comex_10g
    st.metric("MCX vs COMEX-implied (24K, per 10g)", inr(spread), f"{spread / comex_10g * 100:+.2f}%", delta_color="off")
