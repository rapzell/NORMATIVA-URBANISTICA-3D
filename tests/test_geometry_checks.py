from src.rules_engine import geometry_checks


def test_geometry_checks_square():
    square = {
        "type": "Polygon",
        "coordinates": [[
            [0,0],[10,0],[10,10],[0,10],[0,0]
        ]]
    }
    rep = geometry_checks(square)
    assert rep.area == 100.0
    assert rep.perimeter == 40.0
    assert rep.is_valid is True
    assert rep.convexity_ratio == 1.0


def test_geometry_checks_l_shape():
    # Un polígono en L (no convexo)
    poly = {
        "type": "Polygon",
        "coordinates": [[
            [0,0],[6,0],[6,2],[2,2],[2,6],[0,6],[0,0]
        ]]
    }
    rep = geometry_checks(poly)
    assert rep.area == 20.0
    assert rep.is_valid is True
    assert 0.0 < rep.convexity_ratio < 1.0
