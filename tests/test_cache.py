import time

from src import cache


def test_disk_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    cache.disk_set('test', 'k1', {'a': 1})
    assert cache.disk_get('test', 'k1', ttl_s=60) == {'a': 1}


def test_disk_cache_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    cache.disk_set('test', 'k2', 'v')
    path = cache.disk_path('test', 'k2')
    import os
    old = time.time() - 100
    os.utime(path, (old, old))
    assert cache.disk_get('test', 'k2', ttl_s=10) is None
    assert cache.disk_get('test', 'k2', ttl_s=200) == 'v'


def test_disk_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    assert cache.disk_get('test', 'nope', ttl_s=60) is None


def test_cached_producer(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    calls = []

    def produce():
        calls.append(1)
        return {'n': len(calls)}

    assert cache.cached('s', 'k', 60, produce) == {'n': 1}
    assert cache.cached('s', 'k', 60, produce) == {'n': 1}
    assert len(calls) == 1


def test_http_get_retries(monkeypatch):
    attempts = []

    def flaky(req, timeout=15):
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError('boom')

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'ok'
        return R()

    monkeypatch.setattr(cache, 'urlopen', flaky)
    monkeypatch.setattr(cache.time, 'sleep', lambda s: None)
    assert cache.http_get('http://x', retries=3) == b'ok'
    assert len(attempts) == 3
