"""Unit tests for compresscodegen templates."""

import unittest

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


if __name__ == "__main__":
    unittest.main()
