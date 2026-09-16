from src.data_quality import (DataPoint, DataQuality, estimated, measured,
                              official, unavailable)


def test_datapoint_to_dict():
    d = DataPoint(14.2, 'm', DataQuality.MEASURED, 'PNOA LiDAR',
                  source_ref='P90').to_dict()
    assert d['value'] == 14.2
    assert d['unit'] == 'm'
    assert d['data_quality'] == 'measured'
    assert d['quality_label'] == 'Medido'
    assert d['source'] == 'PNOA LiDAR'
    assert d['source_ref'] == 'P90'


def test_quality_levels():
    assert DataQuality.OFFICIAL.value == 'official'
    assert DataQuality.MEASURED.value == 'measured'
    assert DataQuality.ESTIMATED.value == 'estimated'
    assert DataQuality.UNAVAILABLE.value == 'unavailable'


def test_helpers():
    assert official('x', source='SIOTUGA').quality is DataQuality.OFFICIAL
    assert measured(1.0, 'm', 'LiDAR').quality is DataQuality.MEASURED
    assert estimated(3.0, 'm', 'OSM').quality is DataQuality.ESTIMATED
    u = unavailable('LiDAR', notes='sin cobertura').to_dict()
    assert u['value'] is None
    assert u['data_quality'] == 'unavailable'
    assert u['notes'] == 'sin cobertura'
