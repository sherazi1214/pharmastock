from app.routes_products import ProductIn, checked_units, parse_gs1, validate_import

def test_unit_factors_accept_box_strip_tablet():
    units = [ProductIn(name="Example", mrp=20, retail_price=15, units=[
        {"name":"Tablet","factor":1},{"name":"Strip","factor":10},{"name":"Box","factor":100}
    ]).units]
    assert [x[1] for x in checked_units(units[0])] == [1,10,100]

def test_invalid_unit_multiples_rejected():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        checked_units(ProductIn(name="Example", units=[
            {"name":"Tablet","factor":1},{"name":"Strip","factor":7},{"name":"Box","factor":100}
        ]).units)

def test_gs1_full_code_fields():
    result = parse_gs1("01095011015300031727123110BATCH9\x1d21SERIAL7")
    assert result["is_gs1"] is True
    assert result["gtin"] == "09501101530003"
    assert result["expiry"] == "2027-12-31"
    assert result["batch"] == "BATCH9"
    assert result["serial"] == "SERIAL7"

def test_plain_ean_is_not_assumed_gs1():
    result = parse_gs1("8901234567890")
    assert result["is_gs1"] is False
    assert result["batch"] is None

def test_import_5000_rows_and_invalid_data():
    rows = [{"name":f"DEMO Product {i}","barcode":f"DEMO-{i:05}","purchase_price":"2","wholesale_price":"3","retail_price":"4","mrp":"5","unit_name":"Tablet","unit_factor":"1"} for i in range(5000)]
    rows += [{"name":"","retail_price":"1","mrp":"2"},{"name":"Bad price","retail_price":"15","mrp":"10"},{"name":"Negative","purchase_price":"-1","retail_price":"1","mrp":"2"}]
    valid, errors = validate_import(rows)
    assert len(valid) == 5000
    assert len(errors) == 3
    assert all("DEMO" in row["name"] for row in valid[:2])
