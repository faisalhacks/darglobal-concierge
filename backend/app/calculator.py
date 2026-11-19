"""Calculator (SPEC §13). Code only; formula always shown; estimate, not financial advice.

Currency conversion: currencies with an official fixed peg to the US dollar use the peg (published by the issuing
central bank). EUR, GBP and INR use the European Central Bank daily reference rates (free, no key), fetched at startup
and refreshed every 24 h by a background task, cached in memory with the ECB date. A request never waits on the fetch;
if no rate is cached the answer says so, and no rate is ever invented.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET

from .arabic import normalize_text
from .planner import CURRENCIES, parse_amount, _AMOUNT

# Units of currency per 1 USD (official pegs).
PEGS = {"USD": 1.0, "AED": 3.6725, "SAR": 3.75, "QAR": 3.64, "OMR": 0.3845, "BHD": 0.376}
PEG_SOURCE = ("Official USD pegs: AED 3.6725 (CBUAE), SAR 3.75 (SAMA), QAR 3.64 (QCB), OMR 0.3845 (CBO), "
              "BHD 0.376 (CBB)")
PEG_DATE = "fixed peg (unchanged since before 2020)"

PEG_BANK = {"USD": None, "AED": "CBUAE", "SAR": "SAMA", "QAR": "QCB", "OMR": "CBO", "BHD": "CBB"}

# ---- ECB daily reference rates (EUR, GBP, INR). ECB quotes units of currency per 1 EUR; we cross via USD.
log = logging.getLogger("concierge.fx")
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB_CURRENCIES = ("EUR", "GBP", "INR")
ECB_REFRESH_S = 24 * 3600
ECB_RETRY_S = 3600
_LIVE: dict = {"per_usd": {}, "date": None, "fetched_at": None}  # units of currency per 1 USD, from the ECB


class RateUnavailable(Exception):
    """No cached reference rate for this currency (the ECB feed has not been reachable)."""

    def __init__(self, currency: str):
        super().__init__(currency)
        self.currency = currency


def parse_ecb_xml(xml: str) -> tuple[dict[str, float], str]:
    """(units of currency per 1 EUR incl. USD, ECB date) from the eurofxref-daily.xml document."""
    if "<!DOCTYPE" in xml or "<!ENTITY" in xml:
        raise ValueError("unexpected DTD in ECB document")
    root = ET.fromstring(xml)
    rates, date = {}, None
    for el in root.iter():
        if not el.tag.endswith("Cube"):
            continue
        if el.get("time"):
            date = el.get("time")
        if el.get("currency") and el.get("rate"):
            v = float(el.get("rate"))
            if v > 0:
                rates[el.get("currency").upper()] = v
    if not date or "USD" not in rates:
        raise ValueError("ECB document without date or USD rate")
    return rates, date


def set_live_rates(per_eur: dict[str, float], date: str) -> None:
    """Cache EUR/GBP/INR per USD from ECB per-EUR quotes (EUR itself = 1)."""
    usd = per_eur["USD"]
    per_usd = {"EUR": 1.0 / usd}
    for c in ECB_CURRENCIES:
        if c != "EUR" and c in per_eur:
            per_usd[c] = per_eur[c] / usd
    _LIVE.update(per_usd=per_usd, date=date, fetched_at=time.time())


def clear_live_rates() -> None:
    _LIVE.update(per_usd={}, date=None, fetched_at=None)


def live_rates_date() -> str | None:
    return _LIVE["date"]


async def _fetch_ecb_xml() -> str:
    import httpx
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as c:
        r = await c.get(ECB_URL, headers={"User-Agent": "property-concierge-fx/1.0"})
        r.raise_for_status()
        return r.text


async def refresh_live_rates() -> bool:
    """One fetch of the ECB rates. Never raises: on any failure the previous cache (if any) stays."""
    try:
        per_eur, date = parse_ecb_xml(await _fetch_ecb_xml())
        set_live_rates(per_eur, date)
        log.info("ECB reference rates loaded for %s", date)
        return True
    except Exception as e:  # noqa: BLE001 - a rate feed must never break a request or boot
        log.warning("ECB reference rates unavailable: %s", type(e).__name__)
        return False


async def fx_refresh_loop() -> None:
    """Background task: fetch at startup, then every 24 h (retry hourly while there is no cached rate)."""
    while True:
        ok = await refresh_live_rates()
        await asyncio.sleep(ECB_REFRESH_S if (ok or _LIVE["per_usd"]) else ECB_RETRY_S)


def rate_per_usd(cur: str) -> tuple[float, str]:
    """(units of `cur` per 1 USD, source key). Raises ValueError for an unsupported currency and RateUnavailable
    for an ECB currency with no cached rate."""
    cur = cur.upper()
    if cur in PEGS:
        return PEGS[cur], f"peg:{cur}"
    if cur in ECB_CURRENCIES:
        v = _LIVE["per_usd"].get(cur)
        if v is None:
            raise RateUnavailable(cur)
        return v, "ecb"
    raise ValueError("unsupported currency")


def rate_source_label(keys: list, lang: str = "en") -> str:
    out = []
    for k in dict.fromkeys(keys):
        if k == "peg:USD":
            continue
        if k.startswith("peg:"):
            bank = PEG_BANK.get(k[4:])
            out.append(f"official peg ({bank})" if lang == "en" else f"سعر الربط الرسمي ({bank})")
        else:
            out.append(f"ECB reference rate on {_LIVE['date']}" if lang == "en"
                       else f"سعر البنك المركزي الأوروبي المرجعي بتاريخ {_LIVE['date']}")
    return "; ".join(dict.fromkeys(out)) or ("official peg (USD)" if lang == "en" else "سعر الربط الرسمي (دولار)")


def usd_approx(amount, currency):
    """Pegged currencies only (never a market rate): amount in USD rounded to a whole dollar, else None."""
    cur = (currency or "").upper()
    if amount is None or cur not in PEGS:
        return None
    return int(round(float(amount) / PEGS[cur]))


DISCLAIMER = {
    "en": "Estimate only, not financial advice. Confirm all figures with the official sales team.",
    "ar": "تقدير فقط وليس نصيحة مالية. يرجى تأكيد جميع الأرقام مع فريق المبيعات الرسمي.",
}


def _r(v: float) -> float:
    return round(v, 2)


def _fmt(v: float) -> str:
    return f"{int(v):,}" if float(v).is_integer() else f"{v:,.2f}"


def price_per_m2(price: float, area_m2: float, currency: str | None, lang="en") -> dict:
    if area_m2 <= 0:
        raise ValueError("area must be positive")
    res = _r(price / area_m2)
    return {"kind": "price_per_m2", "inputs": {"price": price, "area_m2": area_m2, "currency": currency},
            "result": {"price_per_m2": res, "currency": currency},
            "formula": f"{_fmt(price)} / {_fmt(area_m2)} m² = {_fmt(res)} {currency or ''} per m²".strip(),
            "disclaimer": DISCLAIMER[lang]}


def down_payment(price: float, percent: float, currency: str | None, lang="en") -> dict:
    if not 0 < percent <= 100:
        raise ValueError("percent must be in (0, 100]")
    dp = _r(price * percent / 100)
    rem = _r(price - dp)
    cur = currency or ""
    return {"kind": "down_payment", "inputs": {"price": price, "percent": percent, "currency": currency},
            "result": {"down_payment": dp, "remaining": rem, "currency": currency},
            "formula": f"{_fmt(price)} × {percent:g}% = {_fmt(dp)} {cur}; remaining {_fmt(price)} − {_fmt(dp)} = {_fmt(rem)} {cur}".strip(),
            "disclaimer": DISCLAIMER[lang]}


def installment_split(price: float, n: int, currency: str | None, percent_down: float = 0.0, lang="en") -> dict:
    if n <= 0 or n > 600:
        raise ValueError("number of instalments out of range")
    dp = _r(price * percent_down / 100)
    each = _r((price - dp) / n)
    cur = currency or ""
    formula = (f"({_fmt(price)} − {_fmt(dp)}) / {n} = {_fmt(each)} {cur} per instalment".strip()
               if dp else f"{_fmt(price)} / {n} = {_fmt(each)} {cur} per instalment".strip())
    return {"kind": "installment_split",
            "inputs": {"price": price, "instalments": n, "percent_down": percent_down, "currency": currency},
            "result": {"per_instalment": each, "down_payment": dp, "currency": currency},
            "formula": formula + " (equal split, no interest assumed)",
            "disclaimer": DISCLAIMER[lang]}


def currency_convert(amount: float, src: str, dst: str, lang="en") -> dict:
    src, dst = src.upper(), dst.upper()
    (r_src, k_src), (r_dst, k_dst) = rate_per_usd(src), rate_per_usd(dst)  # may raise RateUnavailable / ValueError
    rate = r_dst / r_src
    res = _r(amount * rate)
    basis = rate_source_label([k_src, k_dst], lang)
    ecb = "ecb" in (k_src, k_dst)
    date = _LIVE["date"] if ecb else PEG_DATE
    if lang == "ar":
        tail = f"(السعر: 1 {src} = {rate:.6g} {dst}، المصدر: {basis}؛ تقريبي وليس نصيحة مالية)"
    else:
        tail = f"(rate: 1 {src} = {rate:.6g} {dst}, source: {basis}; approximate, not financial advice)"
    return {"kind": "currency_convert", "inputs": {"amount": amount, "from": src, "to": dst},
            "result": {"amount": res, "currency": dst, "rate": round(rate, 6), "rate_basis": basis,
                       "rate_source": basis, "rate_date": date, "approximate": True},
            "formula": f"{_fmt(amount)} {src} × {rate:.6g} = {_fmt(res)} {dst} {tail}",
            "disclaimer": DISCLAIMER[lang]}


def mortgage_payment(principal: float, annual_rate_pct: float, years: float, currency: str | None,
                     lang="en") -> dict:
    """Standard amortising loan: M = P·r(1+r)^n / ((1+r)^n − 1), r = annual rate / 12, n = years × 12. The rate is the
    user's own figure: no lender rate is published in the data, so none is ever assumed."""
    if principal <= 0 or not 0 <= annual_rate_pct <= 30 or not 0 < years <= 40:
        raise ValueError("loan inputs out of range")
    n = int(round(years * 12))
    r = annual_rate_pct / 100 / 12
    m = principal / n if r == 0 else principal * r * (1 + r) ** n / ((1 + r) ** n - 1)
    m, total = _r(m), _r(m * n)
    cur = currency or ""
    return {"kind": "mortgage_payment",
            "inputs": {"principal": principal, "annual_rate_pct": annual_rate_pct, "years": years, "currency": currency},
            "result": {"monthly_payment": m, "total_paid": total, "total_interest": _r(total - principal),
                       "currency": currency},
            "formula": (f"{_fmt(principal)} × r(1+r)^n / ((1+r)^n − 1), r = {annual_rate_pct:g}% / 12, n = {n} months "
                        f"= {_fmt(m)} {cur} per month (rate as you gave it; no lender rate is published here)").replace("  ", " "),
            "disclaimer": DISCLAIMER[lang]}


def _amounts(norm: str) -> list[float]:
    out = []
    for m in re.finditer(_AMOUNT, norm):
        tail = norm[m.end():m.end() + 2]
        if "%" in tail or norm[m.end() - 1:m.end()] == "%":
            continue
        v = parse_amount(m.group(1), m.group(2))
        if v is not None:
            out.append(v)
    return out


_AR_CUR_PREFIX = ("وبال", "بال", "لل", "ال", "وب", "ب", "ل", "و")


def currency_of(tok: str):
    """Currency code for a word, with Arabic prefixes: "بالدولار" (in dollars), "باليورو", "الروبية"."""
    c = CURRENCIES.get(tok)
    if c or not re.match(r"[؀-ۿ]", tok):
        return c
    for p in _AR_CUR_PREFIX:
        if tok.startswith(p) and CURRENCIES.get(tok[len(p):]):
            return CURRENCIES[tok[len(p):]]
    return None


def _currencies(norm: str) -> list[str]:
    found = []
    for m in re.finditer(r"[a-z$£€₹]+|[؀-ۿ]+", norm):
        c = currency_of(m.group(0))
        if c:
            found.append(c)
    return found


def parse_and_compute(message: str, lang: str = "en") -> dict | None:
    """Parse a calculation request. Returns a calc payload or None if inputs are missing/unsupported."""
    norm = normalize_text(message)
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", norm)
    curs = _currencies(norm)
    cur = curs[0] if curs else None
    nums = _amounts(norm)
    try:
        yrs = re.search(r"(\d+(?:\.\d+)?)\s*(years?|yrs?|y\b|سنه|سنوات|عاما|عام)", norm)
        if yrs and pct and re.search(r"mortgage|loan|monthly|emi|per month|finance|financing|قرض|تمويل|شهري", norm):
            y, rate = float(yrs.group(1)), float(pct.group(1))
            principal = [v for v in nums if v not in (y, rate)]
            if principal:
                return mortgage_payment(max(principal), rate, y, cur, lang)
        if re.search(r"convert|حول|تحويل|\b(in|to|into) (usd|aed|sar|qar|omr|bhd|eur|gbp|inr|dollars?|euros?|pounds?|rupees?|dirhams?|riyals?)\b|بال(دولار|يورو|ريال|درهم|روبيه)", norm) \
                and len(curs) >= 2 and nums:
            return currency_convert(nums[0], curs[0], curs[1], lang)
        if re.search(r"per (m2|sqm|square)|price per|سعر المتر|للمتر", norm):
            area = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(m2|sqm|square met|م2|متر)", norm)
            if area:
                a = float(area.group(1).replace(",", ""))
                prices = [n for n in nums if n != a]
                if prices:
                    return price_per_m2(prices[0], a, cur, lang)
        inst = re.search(r"(\d+)\s*(?:equal\s+)?(?:monthly\s+|quarterly\s+|yearly\s+)?(install?ments?|payments|months|monthly|اقساط|قسط|شهر)", norm)
        if inst:
            n = int(inst.group(1))
            prices = [v for v in nums if v != n]
            if prices:
                return installment_split(prices[0], n, cur, float(pct.group(1)) if pct else 0.0, lang)
        if pct:
            prices = [v for v in nums if v != float(pct.group(1))]
            if prices:
                return down_payment(max(prices), float(pct.group(1)), cur, lang)
    except (ValueError, ZeroDivisionError):
        return None
    return None
