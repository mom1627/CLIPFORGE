import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import chat_probe as c

class T(unittest.TestCase):
    def test_peaks(self):
        s = [(i * 60, 1.0) for i in range(100)]
        s[40] = (2400, 9.0); s[41] = (2460, 8.0); s[80] = (4800, 6.0)
        self.assertEqual([o for o, _ in c.pick_peaks(s, 5)], [2400, 4800])
    def test_flat_chat_no_peaks(self):
        self.assertEqual(c.pick_peaks([(i * 60, 1.0 + (i % 3) * 0.1) for i in range(100)], 5), [])
    def test_rate(self):
        self.assertAlmostEqual(c.rate_from_offsets([10 + i * 0.5 for i in range(50)], 0), 50 / 24.5, places=2)
if __name__ == "__main__":
    unittest.main()
