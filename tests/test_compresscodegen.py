"""Unit tests for compresscodegen templates."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import compresscodegen


class TemplateTests(unittest.TestCase):
    """Validate critical template content."""

    def setUp(self):
        self.templates = compresscodegen.get_templates()

    def test_backend_templates_include_cstdint(self):
        cpu_src = self.templates["plugins/cpu/CpuBackend.cpp"]
        hip_src = self.templates["plugins/hip/HipBackend.cpp"]
        metal_src = self.templates["plugins/metal/MetalBackend.mm"]

        self.assertIn("#include <cstdint>", cpu_src)
        self.assertIn("#include <cstdint>", hip_src)
        self.assertIn("#include <cstdint>", metal_src)

    def test_controller_templates_are_thread_safe(self):
        header = self.templates["src/CompressorController.hpp"]
        source = self.templates["src/CompressorController.cpp"]

        self.assertIn("~CompressorController()", header)
        self.assertIn("QFuture<void> m_future;", header)
        self.assertIn("#include <QFuture>", header)

        self.assertIn("QPointer<CompressorController>", source)
        self.assertIn("Qt::QueuedConnection", source)
        self.assertIn("m_future = QtConcurrent::run", source)
        self.assertIn("m_future.waitForFinished()", source)

    def test_sample_payload_remains_delta_friendly(self):
        payload = compresscodegen.synthesize_uint32_payload(64)
        repeated = compresscodegen.synthesize_uint32_payload(64)
        deltas = compresscodegen.simulate_delta_compression(payload)

        self.assertEqual(payload, repeated)
        self.assertEqual(len(payload), len(deltas))
        self.assertGreater(max(payload), max(deltas))
        self.assertLess(max(deltas[1:]), 16)

    def test_delta_simulation_matches_cpu_template_contract(self):
        cpu_src = self.templates["plugins/cpu/CpuBackend.cpp"]
        payload = [0xFFFFFFF0, 0xFFFFFFFF, 0x00000005]
        deltas = compresscodegen.simulate_delta_compression(payload)

        self.assertIn("deltas[0] = buf[0];", cpu_src)
        self.assertIn("deltas[i] = buf[i] - buf[i - 1];", cpu_src)
        self.assertEqual(deltas[0], payload[0] & 0xFFFFFFFF)
        self.assertEqual(deltas[1], 0x0000000F)
        self.assertEqual(deltas[2], 0x00000006)

    def test_welcome_launcher_template_is_present(self):
        launcher = self.templates["welcome_launcher.py"]
        self.assertIn("class WelcomeApp", launcher)
        self.assertIn("ctest", launcher)
        self.assertIn("install_deps", launcher)


if __name__ == "__main__":
    unittest.main()
