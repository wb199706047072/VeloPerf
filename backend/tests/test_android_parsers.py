import unittest
import sys
import os

# Add backend to path to import core
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.android_collector import _parse_cpu_from_top, _parse_gpu_from_content

class TestAndroidParsers(unittest.TestCase):

    def test_cpu_parsing_standard(self):
        # Standard top output
        output = """
Tasks: 1 total,   0 running,   1 sleeping,   0 stopped,   0 zombie
Mem:   5855428k total,  5636040k used,   219388k free,    72844k buffers
Swap:  2097148k total,        0k used,  2097148k free,  2665672k cached
800%cpu  23%user   0%nice  20%sys 757%idle   0%iow   0%irq   0%sirq   0%host
  PID USER         PR  NI VIRT  RES  SHR S[%CPU] %MEM     TIME+ ARGS
12345 u0_a123      20   0 1.2G 123M  80M S 10.5   2.1   0:10.50 com.example.app
"""
        self.assertAlmostEqual(_parse_cpu_from_top(output), 10.5)

    def test_cpu_parsing_offset_columns(self):
        # The tricky case where S and %CPU are close or merged in some views
        # Also testing the case where %CPU column index might vary but 'S' is a good anchor
        output = """
Tasks: 2 total,   0 running,   2 sleeping,   0 stopped,   0 zombie
  Mem:    15301M total,    15142M used,      159M free,       21M buffers
 Swap:    15301M total,      520M used,    14780M free,     7783M cached
800%cpu  74%user  11%nice 111%sys 589%idle   0%iow  15%irq   0%sirq   0%host
  PID USER         PR  NI VIRT  RES  SHR S[%CPU] %MEM     TIME+ ARGS
13737 u0_a318      10 -10  39G 293M 146M S 25.9   1.9  28:49.74 com.spreadwin.live.pro
13905 u0_a318      20   0  16G  74M  41M S  0.0   0.4   0:18.91 com.spreadwin.live.pro:pushcore
"""
        self.assertAlmostEqual(_parse_cpu_from_top(output), 25.9)

    def test_cpu_parsing_multiple_processes(self):
        output = """
  PID USER         PR  NI VIRT  RES  SHR S[%CPU] %MEM     TIME+ ARGS
13737 u0_a318      10 -10  39G 293M 146M S 25.9   1.9  28:49.74 com.spreadwin.live.pro
13905 u0_a318      20   0  16G  74M  41M S  5.1   0.4   0:18.91 com.spreadwin.live.pro:pushcore
"""
        self.assertAlmostEqual(_parse_cpu_from_top(output), 31.0)

    def test_gpu_adreno(self):
        # Adreno path
        path = "/sys/class/kgsl/kgsl-3d0/gpubusy"
        # used total
        content = "71894 1209006"
        # 71894 / 1209006 = 0.0594... -> 5.9%
        self.assertEqual(_parse_gpu_from_content(content, path), 5.9)

    def test_gpu_adreno_zero_total(self):
        path = "/sys/class/kgsl/kgsl-3d0/gpubusy"
        content = "0 0"
        self.assertEqual(_parse_gpu_from_content(content, path), 0.0)

    def test_gpu_mali(self):
        path = "/sys/class/misc/mali0/device/utilization"
        content = "42"
        self.assertEqual(_parse_gpu_from_content(content, path), 42.0)

if __name__ == '__main__':
    unittest.main()
