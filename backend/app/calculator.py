"""Calculator (SPEC §13). Code only; formula always shown; estimate, not financial advice.

Currency conversion is limited to currencies with an official fixed peg to the US dollar, so no floating
market rate is ever invented. Each peg is published by the issuing central bank.
"""
from __future__ import annotations

import re

from .arabic import normalize_text
from .planner import CURRENCIES, parse_amount, _AMOUNT

# Units of currency per 1 USD (official pegs).
PEGS = {"USD": 1.0, "AED": 3.6725, "SAR": 3.75, "QAR": 3.64, "OMR": 0.3845, "BHD": 0.376}
PEG_SOURCE = ("Official USD pegs: AED 3.6725 (CBUAE), SAR 3.75 (SAMA), QAR 3.64 (QCB), OMR 0.3845 (CBO), "
              "BHD 0.376 (CBB)")
PEG_DATE = "fixed peg (unchanged since before 2020)"

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
    if src not in PEGS or dst not in PEGS:
        raise ValueError("unsupported currency")
    rate = PEGS[dst] / PEGS[src]
    res = _r(amount * rate)
    return {"kind": "currency_convert", "inputs": {"amount": amount, "from": src, "to": dst},
            "result": {"amount": res, "currency": dst, "rate": round(rate, 6), "rate_basis": PEG_SOURCE,
                       "rate_date": PEG_DATE, "approximate": True},
            "formula": f"{_fmt(amount)} {src} × {rate:.6f} = {_fmt(res)} {dst} (approximate, {PEG_SOURCE})",
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


def _currencies(norm: str) -> list[str]:
    found = []
    for m in re.finditer(r"[a-z$£€]+|[؀-ۿ]+", norm):
        c = CURRENCIES.get(m.group(0))
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
        if re.search(r"convert|حول|تحويل|\bin (usd|aed|sar|qar|omr|bhd|dollars|dirhams|riyals)\b|\bto (usd|aed|sar|qar|omr|bhd)\b", norm) \
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
