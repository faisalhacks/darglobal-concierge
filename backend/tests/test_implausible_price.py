from backend.app.chat import _implausible_price


def test_data_entry_error_row_is_flagged():
    assert _implausible_price({"price_amount": 83_200_000_000, "price_currency": "SAR", "area_m2": 832})


def test_normal_rows_are_kept():
    assert not _implausible_price({"price_amount": 10_178_420, "price_currency": "SAR", "area_m2": 900})
    assert not _implausible_price({"price_amount": 2_000_000, "price_currency": "SAR", "area_m2": None})
    assert not _implausible_price({"price_amount": 2_000_000, "price_currency": "XYZ", "area_m2": 1})


def test_inr_request_without_prices_on_screen_asks_for_a_price():
    from backend.app.planner import FX_NO_PRICE, fx_follow_up
    from backend.app.store import Store  # noqa: F401  (type only)
    class _S:  # no rows needed: nothing priced in history or last_entities
        projects, listings = [], []
        def project_by_id(self, i): return None
        def listing_by_id(self, i): return None
    out = fx_follow_up("Show these prices in INR", [{"role": "user", "content": "hi"},
                                                    {"role": "assistant", "content": "Hello"}], _S(), [])
    assert out == f"{FX_NO_PRICE} INR"
