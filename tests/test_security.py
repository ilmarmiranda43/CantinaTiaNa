from decimal import Decimal

from app.security import (
    hash_password,
    normalize_phone,
    parse_decimal,
    safe_return_url,
    verify_password,
)


def test_password_hash_is_compatible_and_verifiable():
    value = hash_password("SenhaSegura123")
    assert verify_password("SenhaSegura123", value)
    assert not verify_password("senha-errada", value)


def test_phone_normalization_adds_brazil_country_code():
    assert normalize_phone("(11) 99999-9999") == "5511999999999"
    assert normalize_phone("+55 11 99999-9999") == "5511999999999"


def test_return_url_must_be_local():
    assert safe_return_url("/compras") == "/compras"
    assert safe_return_url("https://example.com/roubo") == "/"
    assert safe_return_url("//example.com") == "/"


def test_brazilian_and_database_decimal_formats():
    assert parse_decimal("1.234,56") == Decimal("1234.56")
    assert parse_decimal("1234.56") == Decimal("1234.56")
