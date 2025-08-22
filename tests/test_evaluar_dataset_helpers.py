import unittest

# Ensure module import from project structure
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluar_dataset import _norm, _score, _art_from  # type: ignore


class TestEvaluarDatasetHelpers(unittest.TestCase):
    def test_norm_basic(self):
        self.assertEqual(_norm('  Hola, Mundo!  '), 'hola mundo')
        self.assertEqual(_norm('Árbol Núñez'), 'arbol nunez')  # accents removed
        self.assertEqual(_norm('123 - ABC'), '123 abc')
        self.assertEqual(_norm(''), '')
        self.assertEqual(_norm(None), '')  # type: ignore

    def test_score_recall(self):
        gold = 'El suelo urbanizable es el destinado al crecimiento urbano'
        resp_good = 'El suelo urbanizable es destinado al crecimiento urbano'
        resp_poor = 'Definición no relacionada'
        self.assertGreaterEqual(_score(resp_good, gold), 0.5)
        self.assertLess(_score(resp_poor, gold), 0.5)
        self.assertEqual(_score('', gold), 0.0)
        self.assertEqual(_score(resp_good, ''), 0.0)

    def test_art_from(self):
        self.assertEqual(_art_from('según Artículo 17'), 17)
        self.assertEqual(_art_from('ver articulo 32'), 32)
        self.assertIsNone(_art_from('sin referencia'))


if __name__ == '__main__':
    unittest.main()
