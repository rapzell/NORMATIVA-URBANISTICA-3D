from src.volume import compute_building_envelope, VolumeParams


def test_volume_basic_square_with_setback():
    square = {
        "type": "Polygon",
        "coordinates": [[
            [0,0],[10,0],[10,10],[0,10],[0,0]
        ]]
    }
    feat = compute_building_envelope(square, VolumeParams(altura_maxima_m=12.0, retranqueo_min_m=1.0))
    assert feat is not None
    props = feat["properties"]
    assert props["height_m"] == 12.0
    assert props["setback_m"] == 1.0
    # Área esperada: (10-2)^2 = 64
    assert abs(props["area_m2"] - 64.0) < 1e-6


essentially_empty = {
    "type": "Polygon",
    "coordinates": [[
        [0,0],[2,0],[2,2],[0,2],[0,0]
    ]]
}


def test_volume_full_erosion_returns_none():
    # Setback mayor que semiancho -> envelope None
    feat = compute_building_envelope(essentially_empty, VolumeParams(altura_maxima_m=10.0, retranqueo_min_m=2.0))
    assert feat is None
