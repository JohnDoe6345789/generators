#!/usr/bin/env python3
"""
Tkinter GUI project generator for a Qt6 QML + plugin-based compression app.

- Lets you pick a base folder.
- Generates the entire gpu_compress_project tree there.
- Shows the resulting file tree in a Tkinter Treeview.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent
import threading
from typing import Sequence
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


UINT32_MASK = 0xFFFFFFFF


def synthesize_uint32_payload(size: int = 128) -> list[int]:
    """Return deterministic, delta-friendly uint32 data.

    The generated payload mimics slowly changing sensor data so the deltas
    produced by the C++ templates remain small and highly compressible.
    """

    if size <= 0:
        return []

    payload: list[int] = []
    current = 0
    for index in range(size):
        stride = ((index % 5) + 1)
        if index % 24 == 0:
            stride += 2
        current = (current + stride) & UINT32_MASK
        payload.append(current)
    return payload


def simulate_delta_compression(values: Sequence[int]) -> list[int]:
    """Mimic the CpuBackend delta loop using uint32 arithmetic."""

    if not values:
        return []

    deltas: list[int] = []
    prev = 0
    for idx, raw in enumerate(values):
        value = raw & UINT32_MASK
        if idx == 0:
            delta = value
        else:
            delta = (value - prev) & UINT32_MASK
        deltas.append(delta)
        prev = value
    return deltas


# ======================================================================
# Template data (from the "godlike" generator)
# ======================================================================

def get_templates():
    CMAKELISTS_TOP = dedent(
        r"""
        cmake_minimum_required(VERSION 3.20)
        project(gpu_compress_project LANGUAGES CXX)

        set(CMAKE_CXX_STANDARD 17)
        set(CMAKE_CXX_STANDARD_REQUIRED ON)

        find_package(Qt6 COMPONENTS Core Quick Qml REQUIRED)

        qt_standard_project_setup()

        add_subdirectory(src)
        add_subdirectory(plugins/cpu)
        add_subdirectory(plugins/hip)
        add_subdirectory(plugins/metal)
        """
    )

    CMAKELISTS_SRC = dedent(
        r"""
        add_library(backend_interface INTERFACE ICompressorBackend.hpp)
        target_include_directories(backend_interface INTERFACE ${CMAKE_CURRENT_SOURCE_DIR})

        add_executable(gpu_compress
            main.cpp
            CompressorController.cpp
            CompressorController.hpp
            PluginLoader.cpp
            PluginLoader.hpp
        )

        qt_add_qml_module(gpu_compress
            URI GPUCompress
            VERSION 1.0
            QML_FILES
                ../qml/MainWindow.qml
        )

        target_link_libraries(gpu_compress
            PRIVATE
                Qt6::Core
                Qt6::Quick
                Qt6::Qml
                backend_interface
        )

        # Where plugins will be placed
        target_compile_definitions(gpu_compress
            PRIVATE
                PLUGIN_DIR="${CMAKE_BINARY_DIR}/plugins"
        )

        install(TARGETS gpu_compress)
        """
    )

    ICOMPR_HPP = dedent(
        r"""
        #pragma once

        #include <QString>
        #include <functional>
        #include <QtPlugin>

        class ICompressorBackend {
        public:
            virtual ~ICompressorBackend() = default;

            // Stable ID, e.g. "cpu", "hip", "metal"
            virtual QString id() const = 0;

            // Human readable name
            virtual QString name() const = 0;

            // Simple one-shot compression: input file -> output file
            virtual void compress(const QString &input,
                                  const QString &output,
                                  std::function<void(double)> progress,
                                  std::function<void(QString)> status) = 0;
        };

        #define ICompressorBackend_iid "com.example.gpucompress.ICompressorBackend/1.0"
        Q_DECLARE_INTERFACE(ICompressorBackend, ICompressorBackend_iid)
        """
    )

    PLUGIN_LOADER_HPP = dedent(
        r"""
        #pragma once

        #include <QObject>
        #include <QVector>
        #include <QString>

        #include "ICompressorBackend.hpp"

        class PluginLoader : public QObject {
            Q_OBJECT
        public:
            explicit PluginLoader(QObject *parent = nullptr);

            void discover();
            ICompressorBackend *backend() const;
            QString backendName() const;

        private:
            void selectBest();

            QVector<ICompressorBackend*> m_backends;
            ICompressorBackend *m_selected {nullptr};
        };
        """
    )

    PLUGIN_LOADER_CPP = dedent(
        r"""
        #include "PluginLoader.hpp"

        #include <QDir>
        #include <QPluginLoader>
        #include <QDebug>

        PluginLoader::PluginLoader(QObject *parent)
            : QObject(parent) {}

        void PluginLoader::discover() {
            const QString dirPath = QString::fromUtf8(PLUGIN_DIR);
            QDir dir(dirPath);
            if (!dir.exists()) {
                qWarning() << "Plugin directory does not exist:" << dirPath;
                return;
            }

        #if defined(Q_OS_WIN)
            const QStringList patterns = { "*.dll" };
        #elif defined(Q_OS_MAC)
            const QStringList patterns = { "*.dylib" };
        #else
            const QStringList patterns = { "*.so" };
        #endif

            const auto files = dir.entryList(patterns, QDir::Files);
            for (const auto &file : files) {
                const QString path = dir.absoluteFilePath(file);
                QPluginLoader loader(path);
                QObject *obj = loader.instance();
                if (!obj) {
                    qWarning() << "Failed to load plugin" << path << loader.errorString();
                    continue;
                }

                auto backend = qobject_cast<ICompressorBackend*>(obj);
                if (!backend) {
                    qWarning() << "Object in" << path << "does not implement ICompressorBackend";
                    continue;
                }

                m_backends.push_back(backend);
            }

            selectBest();
        }

        void PluginLoader::selectBest() {
            m_selected = nullptr;

            // Priority order: HIP > Metal > CPU > anything else
            auto pickById = [this](const QString &target) -> ICompressorBackend* {
                for (auto *b : m_backends) {
                    if (b->id() == target) return b;
                }
                return nullptr;
            };

            m_selected = pickById(QStringLiteral("hip"));
            if (!m_selected) {
                m_selected = pickById(QStringLiteral("metal"));
            }
            if (!m_selected) {
                m_selected = pickById(QStringLiteral("cpu"));
            }
            if (!m_selected && !m_backends.isEmpty()) {
                m_selected = m_backends.first();
            }
        }

        ICompressorBackend *PluginLoader::backend() const {
            return m_selected;
        }

        QString PluginLoader::backendName() const {
            if (!m_selected) return QStringLiteral("<none>");
            return m_selected->name();
        }
        """
    )

    CONTROLLER_HPP = dedent(
        r"""
        #pragma once

        #include <QFuture>
        #include <QObject>
        #include <QString>
        #include <QtConcurrent>

        #include "PluginLoader.hpp"

        class CompressorController : public QObject {
            Q_OBJECT

            Q_PROPERTY(QString inputFile READ inputFile WRITE setInputFile NOTIFY inputFileChanged)
            Q_PROPERTY(QString outputFile READ outputFile WRITE setOutputFile NOTIFY outputFileChanged)
            Q_PROPERTY(double progress READ progress NOTIFY progressChanged)
            Q_PROPERTY(QString status READ status NOTIFY statusChanged)
            Q_PROPERTY(QString backendName READ backendName NOTIFY backendNameChanged)

        public:
            explicit CompressorController(QObject *parent = nullptr);
            ~CompressorController();

            QString inputFile() const { return m_input; }
            QString outputFile() const { return m_output; }
            double progress() const { return m_progress; }
            QString status() const { return m_status; }
            QString backendName() const { return m_backendName; }

        public slots:
            void pickInput();
            void pickOutput();
            void startCompression();

            void setInputFile(const QString &f);
            void setOutputFile(const QString &f);

        signals:
            void inputFileChanged();
            void outputFileChanged();
            void progressChanged();
            void statusChanged();
            void backendNameChanged();

        private:
            QString m_input;
            QString m_output;
            double m_progress = 0.0;
            QString m_status = "Idle";
            QString m_backendName = "<none>";

            PluginLoader m_loader;
            QFuture<void> m_future;
        };
        """
    )

    CONTROLLER_CPP = dedent(
        r"""
        #include "CompressorController.hpp"

        #include <QFileDialog>
        #include <QDebug>
        #include <QMetaObject>
        #include <QPointer>

        CompressorController::CompressorController(QObject *parent)
            : QObject(parent) {
            m_loader.discover();
            m_backendName = m_loader.backendName();
            emit backendNameChanged();
        }

        CompressorController::~CompressorController() {
            if (m_future.isRunning()) {
                m_future.waitForFinished();
            }
        }

        void CompressorController::pickInput() {
            auto f = QFileDialog::getOpenFileName(nullptr, "Pick input file");
            if (!f.isEmpty()) setInputFile(f);
        }

        void CompressorController::pickOutput() {
            auto f = QFileDialog::getSaveFileName(nullptr, "Pick output file");
            if (!f.isEmpty()) setOutputFile(f);
        }

        void CompressorController::setInputFile(const QString &f) {
            m_input = f;
            emit inputFileChanged();
        }

        void CompressorController::setOutputFile(const QString &f) {
            m_output = f;
            emit outputFileChanged();
        }

        void CompressorController::startCompression() {
            if (m_future.isRunning()) {
                m_status = "Compression already running";
                emit statusChanged();
                return;
            }

            auto *backend = m_loader.backend();
            if (!backend) {
                m_status = "No backend plugins found";
                emit statusChanged();
                return;
            }

            m_status = QStringLiteral("Running on ") + backend->name();
            m_progress = 0.0;
            emit statusChanged();
            emit progressChanged();

            const QString input = m_input;
            const QString output = m_output;

            QPointer<CompressorController> guard(this);
            auto reportProgress = [guard](double p) {
                if (!guard) return;
                QMetaObject::invokeMethod(
                    guard,
                    [guard, p]() {
                        guard->m_progress = p;
                        emit guard->progressChanged();
                    },
                    Qt::QueuedConnection
                );
            };

            auto reportStatus = [guard](const QString &msg) {
                if (!guard) return;
                QMetaObject::invokeMethod(
                    guard,
                    [guard, msg]() {
                        guard->m_status = msg;
                        emit guard->statusChanged();
                    },
                    Qt::QueuedConnection
                );
            };

            m_future = QtConcurrent::run([backend, input, output, reportProgress, reportStatus] {
                backend->compress(input, output, reportProgress, reportStatus);
            });
        }
        """
    )

    MAIN_CPP = dedent(
        r"""
        #include <QGuiApplication>
        #include <QQmlApplicationEngine>
        #include <QQmlContext>

        #include "CompressorController.hpp"

        int main(int argc, char *argv[]) {
            QGuiApplication app(argc, argv);

            CompressorController controller;

            QQmlApplicationEngine engine;
            engine.rootContext()->setContextProperty("controller", &controller);
            engine.loadFromModule("GPUCompress", "MainWindow");

            if (engine.rootObjects().isEmpty())
                return -1;

            return app.exec();
        }
        """
    )

    MAINWINDOW_QML = dedent(
        r"""
        import QtQuick
        import QtQuick.Controls
        import QtQuick.Layouts

        Window {
            width: 720
            height: 460
            visible: true
            title: "GPU Compressor (Plugin-based)"

            ColumnLayout {
                anchors.fill: parent
                spacing: 12
                padding: 20

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Label { text: "Backend:" }
                    Label { text: controller.backendName }
                }

                TextField {
                    id: inputField
                    Layout.fillWidth: true
                    placeholderText: "Input file"
                    text: controller.inputFile
                }
                Button {
                    text: "Pick Input"
                    onClicked: controller.pickInput()
                }

                TextField {
                    id: outputField
                    Layout.fillWidth: true
                    placeholderText: "Output file"
                    text: controller.outputFile
                }
                Button {
                    text: "Pick Output"
                    onClicked: controller.pickOutput()
                }

                Button {
                    text: "Start Compression"
                    onClicked: controller.startCompression()
                }

                ProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: 1
                    value: controller.progress
                }

                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: controller.status
                }
            }
        }
        """
    )

    README_MD = dedent(
        r"""
        # GPU Compress Project (Qt6 + Plugin Backends)

        Generated by `generate_gpu_compress_project.py` (Tkinter GUI version).

        ## Structure

        - `src/`
          - Qt6 QML GUI
          - Plugin loader + controller
        - `plugins/cpu/`
          - Always-built CPU backend
        - `plugins/hip/`
          - HIP AMD backend (Windows/Linux, built only if HIP found)
        - `plugins/metal/`
          - Metal backend (macOS, uses CPU delta stub but checks for Metal device)
        - `qml/`
          - `MainWindow.qml` (Qt Quick UI)
        - `scripts/`
          - Build, run, and dependency install helpers

        ## Quick Start

        ### Linux

        ```bash
        cd gpu_compress_project
        ./scripts/install_deps.sh
        ./scripts/build.sh
        ./scripts/run.sh
        ```

        ### macOS (Apple Silicon)

        ```bash
        cd gpu_compress_project
        ./scripts/install_deps_mac.sh
        ./scripts/build.sh
        ./scripts/run.sh
        ```

        ### Windows (x64, PowerShell)

        ```powershell
        cd gpu_compress_project
        .\scripts\install_deps.ps1
        .\scripts\build.bat
        .\scripts\run.bat
        ```

        Backend priority is: HIP > Metal > CPU.
        """
    )

    CMAKELISTS_CPU = dedent(
        r"""
        add_library(cpu_backend SHARED
            CpuBackend.cpp
            CpuBackend.hpp
        )

        target_link_libraries(cpu_backend PRIVATE Qt6::Core backend_interface)
        target_include_directories(cpu_backend PRIVATE ${CMAKE_SOURCE_DIR}/src)

        set_target_properties(cpu_backend PROPERTIES
            LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/plugins
        )
        """
    )

    CPU_HPP = dedent(
        r"""
        #pragma once

        #include <QObject>
        #include "ICompressorBackend.hpp"

        class CpuBackend : public QObject, public ICompressorBackend {
            Q_OBJECT
            Q_PLUGIN_METADATA(IID ICompressorBackend_iid)
            Q_INTERFACES(ICompressorBackend)

        public:
            QString id() const override { return QStringLiteral("cpu"); }
            QString name() const override { return QStringLiteral("CPU Backend"); }

            void compress(const QString &input,
                          const QString &output,
                          std::function<void(double)> progress,
                          std::function<void(QString)> status) override;
        };
        """
    )

    CPU_CPP = dedent(
        r"""
        #include "CpuBackend.hpp"

        #include <cstdint>
        #include <fstream>
        #include <vector>

        void CpuBackend::compress(const QString &inputPath,
                                  const QString &outputPath,
                                  std::function<void(double)> progress,
                                  std::function<void(QString)> status) {
            status("CPU: reading...");

            std::ifstream in(inputPath.toStdString(), std::ios::binary);
            if (!in) {
                status("CPU: failed to open input");
                progress(1.0);
                return;
            }

            in.seekg(0, std::ios::end);
            std::streamsize size = in.tellg();
            in.seekg(0, std::ios::beg);

            if (size % static_cast<std::streamsize>(sizeof(uint32_t)) != 0) {
                status("CPU: input size not multiple of 4 bytes");
            }

            const std::size_t n =
                static_cast<std::size_t>(size / sizeof(uint32_t));
            std::vector<uint32_t> buf(n);
            if (n > 0) {
                in.read(reinterpret_cast<char*>(buf.data()), size);
            }

            status("CPU: computing deltas...");
            std::vector<uint32_t> deltas(n);
            if (n > 0) {
                deltas[0] = buf[0];
                for (std::size_t i = 1; i < n; ++i) {
                    deltas[i] = buf[i] - buf[i - 1];
                    if (n > 0 && i % (n / 10 + 1) == 0) {
                        progress(static_cast<double>(i) / n);
                    }
                }
            }

            status("CPU: writing...");
            std::ofstream out(outputPath.toStdString(), std::ios::binary);
            if (n > 0) {
                out.write(
                    reinterpret_cast<const char*>(deltas.data()),
                    static_cast<std::streamsize>(n * sizeof(uint32_t)));
            }

            progress(1.0);
            status("CPU: done");
        }
        """
    )

    CMAKELISTS_HIP = dedent(
        r"""
        if(NOT APPLE)
            find_package(hip QUIET)
            if(NOT hip_FOUND)
                message(STATUS "HIP not found, hip_backend will not be built")
                return()
            endif()

            add_library(hip_backend SHARED
                HipBackend.cpp
                HipBackend.hpp
            )

            target_link_libraries(hip_backend PRIVATE Qt6::Core backend_interface hip::device)
            target_include_directories(hip_backend PRIVATE ${CMAKE_SOURCE_DIR}/src)

            set_target_properties(hip_backend PROPERTIES
                LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/plugins
            )
        endif()
        """
    )

    HIP_HPP = dedent(
        r"""
        #pragma once

        #include <QObject>
        #include "ICompressorBackend.hpp"

        class HipBackend : public QObject, public ICompressorBackend {
            Q_OBJECT
            Q_PLUGIN_METADATA(IID ICompressorBackend_iid)
            Q_INTERFACES(ICompressorBackend)

        public:
            QString id() const override { return QStringLiteral("hip"); }
            QString name() const override { return QStringLiteral("HIP AMD Backend"); }

            void compress(const QString &input,
                          const QString &output,
                          std::function<void(double)> progress,
                          std::function<void(QString)> status) override;
        };
        """
    )

    HIP_CPP = dedent(
        r"""
        #include "HipBackend.hpp"

        #include <cstdint>
        #include <hip/hip_runtime.h>
        #include <fstream>
        #include <vector>

        __global__ void hipDeltaKernel(const uint32_t *input, uint32_t *deltas, size_t n) {
            size_t i = blockIdx.x * blockDim.x + threadIdx.x;
            if (i >= n) return;
            deltas[i] = (i == 0) ? input[0] : input[i] - input[i - 1];
        }

        void HipBackend::compress(const QString &inputPath,
                                  const QString &outputPath,
                                  std::function<void(double)> progress,
                                  std::function<void(QString)> status) {
            status("HIP: reading...");

            std::ifstream in(inputPath.toStdString(), std::ios::binary);
            if (!in) {
                status("HIP: failed to open input");
                progress(1.0);
                return;
            }

            in.seekg(0, std::ios::end);
            std::streamsize size = in.tellg();
            in.seekg(0, std::ios::beg);

            const std::size_t n =
                static_cast<std::size_t>(size / sizeof(uint32_t));
            std::vector<uint32_t> buf(n);
            if (n > 0) {
                in.read(reinterpret_cast<char*>(buf.data()), size);
            }

            status("HIP: uploading...");
            uint32_t *d_in = nullptr;
            uint32_t *d_out = nullptr;
            hipMalloc(&d_in, n * sizeof(uint32_t));
            hipMalloc(&d_out, n * sizeof(uint32_t));
            hipMemcpy(d_in, buf.data(), n * sizeof(uint32_t), hipMemcpyHostToDevice);

            const int block = 256;
            const int grid = static_cast<int>((n + block - 1) / block);
            hipLaunchKernelGGL(
                hipDeltaKernel, dim3(grid), dim3(block), 0, 0, d_in, d_out, n);
            hipDeviceSynchronize();

            status("HIP: downloading...");
            std::vector<uint32_t> deltas(n);
            if (n > 0) {
                hipMemcpy(deltas.data(), d_out, n * sizeof(uint32_t),
                          hipMemcpyDeviceToHost);
            }

            hipFree(d_in);
            hipFree(d_out);

            status("HIP: writing...");
            std::ofstream out(outputPath.toStdString(), std::ios::binary);
            if (n > 0) {
                out.write(
                    reinterpret_cast<const char*>(deltas.data()),
                    static_cast<std::streamsize>(n * sizeof(uint32_t)));
            }

            progress(1.0);
            status("HIP: done");
        }
        """
    )

    CMAKELISTS_METAL = dedent(
        r"""
        if(APPLE)
            enable_language(OBJCXX)

            add_library(metal_backend SHARED
                MetalBackend.mm
                MetalBackend.hpp
            )

            target_link_libraries(metal_backend
                PRIVATE
                    Qt6::Core
                    backend_interface
                    "-framework Metal"
                    "-framework Foundation"
            )

            target_include_directories(metal_backend PRIVATE ${CMAKE_SOURCE_DIR}/src)

            set_target_properties(metal_backend PROPERTIES
                LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/plugins
            )
        endif()
        """
    )

    METAL_HPP = dedent(
        r"""
        #pragma once

        #include <QObject>
        #include "ICompressorBackend.hpp"

        class MetalBackend : public QObject, public ICompressorBackend {
            Q_OBJECT
            Q_PLUGIN_METADATA(IID ICompressorBackend_iid)
            Q_INTERFACES(ICompressorBackend)

        public:
            QString id() const override { return QStringLiteral("metal"); }
            QString name() const override { return QStringLiteral("Metal Backend"); }

            void compress(const QString &input,
                          const QString &output,
                          std::function<void(double)> progress,
                          std::function<void(QString)> status) override;
        };
        """
    )

    METAL_MM = dedent(
        r"""
        #import "MetalBackend.hpp"
        #import <Metal/Metal.h>
        #import <Foundation/Foundation.h>

        #include <cstdint>
        #include <fstream>
        #include <vector>

        @implementation MetalBackend

        void MetalBackend::compress(const QString &inputPath,
                                    const QString &outputPath,
                                    std::function<void(double)> progress,
                                    std::function<void(QString)> status) {
            status("Metal: reading...");

            std::ifstream in(inputPath.toStdString(), std::ios::binary);
            if (!in) {
                status("Metal: failed to open input");
                progress(1.0);
                return;
            }

            in.seekg(0, std::ios::end);
            std::streamsize size = in.tellg();
            in.seekg(0, std::ios::beg);

            const std::size_t n =
                static_cast<std::size_t>(size / sizeof(uint32_t));
            std::vector<uint32_t> buf(n);
            if (n > 0) {
                in.read(reinterpret_cast<char*>(buf.data()), size);
            }

            id<MTLDevice> device = MTLCreateSystemDefaultDevice();
            if (!device) {
                status("Metal: no device, falling back to CPU delta");
            } else {
                status("Metal: device present (using CPU stub, GPU pipeline TODO)");
            }

            std::vector<uint32_t> deltas(n);
            if (n > 0) {
                deltas[0] = buf[0];
                for (std::size_t i = 1; i < n; ++i) {
                    deltas[i] = buf[i] - buf[i - 1];
                    if (n > 0 && i % (n / 10 + 1) == 0) {
                        progress(static_cast<double>(i) / n);
                    }
                }
            }

            std::ofstream out(outputPath.toStdString(), std::ios::binary);
            if (n > 0) {
                out.write(
                    reinterpret_cast<const char*>(deltas.data()),
                    static_cast<std::streamsize>(n * sizeof(uint32_t)));
            }

            progress(1.0);
            status("Metal: done (CPU stub)");
        }

        @end
        """
    )

    SCRIPTS_BUILD_SH = dedent(
        r"""
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
        BUILD_DIR="${ROOT_DIR}/build"

        mkdir -p "${BUILD_DIR}"
        cd "${BUILD_DIR}"

        cmake ..
        cmake --build . --parallel
        """
    )

    SCRIPTS_RUN_SH = dedent(
        r"""
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
        BUILD_DIR="${ROOT_DIR}/build"

        "${BUILD_DIR}/gpu_compress"
        """
    )

    SCRIPTS_INSTALL_LINUX_SH = dedent(
        r"""
        #!/usr/bin/env bash
        set -euo pipefail

        echo "=== Installing dependencies for Linux ==="

        have_cmd() {
            command -v "$1" >/dev/null 2>&1
        }

        if have_cmd apt; then
            sudo apt update
            sudo apt install -y cmake ninja-build g++ git \
                qt6-base-dev qt6-declarative-dev
            echo "Optional: HIP/ROCm for AMD GPUs (rocm-hip-sdk, etc.)"
            exit 0
        fi

        if have_cmd dnf; then
            sudo dnf install -y cmake ninja-build gcc-c++ git \
                qt6-qtbase-devel qt6-qtdeclarative-devel
            echo "Optional: HIP/ROCm for AMD GPUs (hip-devel)"
            exit 0
        fi

        if have_cmd pacman; then
            sudo pacman -Sy --noconfirm cmake ninja gcc git \
                qt6-base qt6-declarative
            echo "Optional: HIP/ROCm for AMD GPUs (hip-runtime-amd)"
            exit 0
        fi

        echo "Unsupported distro. Please install:"
        echo " - Qt6 (base + QML/Quick)"
        echo " - CMake, Ninja, C++17 compiler, Git"
        echo " - Optional: HIP/ROCm if you have an AMD GPU."
        """
    )

    SCRIPTS_BUILD_BAT = dedent(
        r"""
        @echo off
        setlocal enabledelayedexpansion

        set ROOT_DIR=%~dp0..
        set BUILD_DIR=%ROOT_DIR%\build

        if not exist "%BUILD_DIR%" (
            mkdir "%BUILD_DIR%"
        )

        cd /d "%BUILD_DIR%"
        cmake ..
        cmake --build . --config Release

        endlocal
        """
    )

    SCRIPTS_RUN_BAT = dedent(
        r"""
        @echo off
        setlocal enabledelayedexpansion

        set ROOT_DIR=%~dp0..
        set BUILD_DIR=%ROOT_DIR%\build

        cd /d "%BUILD_DIR%"
        gpu_compress.exe

        endlocal
        """
    )

    SCRIPTS_INSTALL_WIN_PS1 = dedent(
        r"""
        param(
            [switch]$Force
        )

        Write-Host "=== Installing dependencies for Windows ===" -ForegroundColor Cyan

        function Ensure-Admin {
            $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
            $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
            if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
                Write-Host "Requesting UAC elevation..."
                $psi = New-Object System.Diagnostics.ProcessStartInfo
                $psi.FileName = "powershell"
                $psi.Arguments = "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
                $psi.Verb = "runAs"
                [System.Diagnostics.Process]::Start($psi) | Out-Null
                exit
            }
        }

        Ensure-Admin

        function Have-Command($name) {
            return Get-Command $name -ErrorAction SilentlyContinue
        }

        if (Have-Command "winget") {
            Write-Host "Using winget to install tools..."

            winget install -e --id Kitware.CMake      --source winget
            winget install -e --id Ninja.Ninja        --source winget
            winget install -e --id Qt.Qt6.6          --source winget -h
            winget install -e --id Git.Git            --source winget

            Write-Host "Consider installing Visual Studio Build Tools for MSVC:"
            Write-Host "  winget install -e --id Microsoft.VisualStudio.2022.BuildTools"
            Write-Host "For AMD GPU + HIP/ROCm, install AMD's ROCm/HIP stack separately."
        }
        elseif (Have-Command "choco") {
            Write-Host "Using Chocolatey to install tools..."

            choco install -y cmake ninja git
            Write-Host "Install Qt6 via online/offline installer:"
            Write-Host "  https://www.qt.io/download-open-source"
            Write-Host "For AMD GPU + HIP, install ROCm/HIP via AMD docs."
        }
        else {
            Write-Host "Neither winget nor choco found."
            Write-Host "Please install manually:"
            Write-Host " - Qt 6 (Desktop)"
            Write-Host " - CMake"
            Write-Host " - Ninja"
            Write-Host " - MSVC (e.g., Visual Studio Build Tools)"
            Write-Host " - Optional: HIP/ROCm if you have an AMD GPU."
        }
        """
    )

    SCRIPTS_INSTALL_MAC_SH = dedent(
        r"""
        #!/usr/bin/env bash
        set -euo pipefail

        echo "=== Installing dependencies for macOS ==="

        if ! command -v brew >/dev/null 2>&1; then
            echo "Homebrew not found. Install from https://brew.sh/"
            exit 1
        fi

        brew update
        brew install cmake ninja git qt

        echo "Xcode Command Line Tools may also be required:"
        echo "  xcode-select --install"
        echo "Metal backend is built, but currently uses a CPU delta stub."
        """
    )

    return {
        "CMakeLists.txt": CMAKELISTS_TOP,
        "src/CMakeLists.txt": CMAKELISTS_SRC,
        "src/ICompressorBackend.hpp": ICOMPR_HPP,
        "src/PluginLoader.hpp": PLUGIN_LOADER_HPP,
        "src/PluginLoader.cpp": PLUGIN_LOADER_CPP,
        "src/CompressorController.hpp": CONTROLLER_HPP,
        "src/CompressorController.cpp": CONTROLLER_CPP,
        "src/main.cpp": MAIN_CPP,
        "qml/MainWindow.qml": MAINWINDOW_QML,
        "README.md": README_MD,
        "plugins/cpu/CMakeLists.txt": CMAKELISTS_CPU,
        "plugins/cpu/CpuBackend.hpp": CPU_HPP,
        "plugins/cpu/CpuBackend.cpp": CPU_CPP,
        "plugins/hip/CMakeLists.txt": CMAKELISTS_HIP,
        "plugins/hip/HipBackend.hpp": HIP_HPP,
        "plugins/hip/HipBackend.cpp": HIP_CPP,
        "plugins/metal/CMakeLists.txt": CMAKELISTS_METAL,
        "plugins/metal/MetalBackend.hpp": METAL_HPP,
        "plugins/metal/MetalBackend.mm": METAL_MM,
        "scripts/build.sh": SCRIPTS_BUILD_SH,
        "scripts/run.sh": SCRIPTS_RUN_SH,
        "scripts/install_deps.sh": SCRIPTS_INSTALL_LINUX_SH,
        "scripts/build.bat": SCRIPTS_BUILD_BAT,
        "scripts/run.bat": SCRIPTS_RUN_BAT,
        "scripts/install_deps.ps1": SCRIPTS_INSTALL_WIN_PS1,
        "scripts/install_deps_mac.sh": SCRIPTS_INSTALL_MAC_SH,
    }


# ======================================================================
# Core generation logic
# ======================================================================

def write_file(root: Path, rel_path: str, content: str) -> None:
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def make_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        path.chmod(mode | 0o111)
    except OSError:
        pass


def generate_project(base_dir: Path, log) -> Path:
    project_root = base_dir / "gpu_compress_project"
    templates = get_templates()

    log(f"Generating project at: {project_root}")
    for rel, content in templates.items():
        write_file(project_root, rel, content)
        log(f"  wrote {rel}")

    # Make unix scripts executable
    for rel in (
        "scripts/build.sh",
        "scripts/run.sh",
        "scripts/install_deps.sh",
        "scripts/install_deps_mac.sh",
    ):
        p = project_root / rel
        if p.exists():
            make_executable(p)
            log(f"  chmod +x {rel}")

    log("Generation complete.")
    return project_root


# ======================================================================
# Tkinter GUI
# ======================================================================


class WelcomeLauncher(tk.Toplevel):
    """Launcher window that orchestrates install/build/run/test commands."""

    def __init__(self, master, project_getter, on_close):
        super().__init__(master)
        self.title("GPU Compress Welcome Launcher")
        self.geometry("640x420")

        self._project_getter = project_getter
        self._on_close = on_close
        self._command_thread: threading.Thread | None = None

        self.path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Idle")

        self._build_widgets()
        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self.refresh_project_path()

    def _build_widgets(self) -> None:
        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(container, text="Project location:").pack(anchor=tk.W)
        ttk.Label(
            container, textvariable=self.path_var, wraplength=600
        ).pack(anchor=tk.W, pady=(0, 8))

        ttk.Label(container, text="Actions:").pack(anchor=tk.W)
        button_frame = ttk.Frame(container)
        button_frame.pack(fill=tk.X, pady=(0, 10))

        self._buttons = []
        for text, handler in [
            ("Install Dependencies", self._on_install),
            ("Build Program", self._on_build),
            ("Run Program", self._on_run),
            ("Run Tests", self._on_test),
        ]:
            btn = ttk.Button(button_frame, text=text, command=handler)
            btn.pack(fill=tk.X, pady=2)
            self._buttons.append(btn)

        ttk.Label(container, text="Status:").pack(anchor=tk.W)
        ttk.Label(container, textvariable=self.status_var).pack(
            anchor=tk.W, pady=(0, 8)
        )

        log_frame = ttk.Frame(container)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, wrap=tk.NONE, height=10)
        scrollbar = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.log_text.yview
        )
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _handle_close(self) -> None:
        if self._command_thread:
            messagebox.showinfo(
                "Command running", "Wait for the current command to finish."
            )
            return
        self._on_close()
        self.destroy()

    def refresh_project_path(self) -> None:
        root = self._project_getter()
        if root is None:
            self.path_var.set("Generate a project to enable launcher actions.")
            state = tk.DISABLED
        else:
            self.path_var.set(str(root))
            state = tk.NORMAL
        for btn in self._buttons:
            btn.configure(state=state)

    def _ensure_project_root(self) -> Path | None:
        root = self._project_getter()
        if root is None:
            messagebox.showerror(
                "Project missing",
                "Generate the project before using the launcher.",
            )
            return None
        return root

    def _on_install(self) -> None:
        self._run_action("Installing dependencies", self._install_command)

    def _on_build(self) -> None:
        self._run_action("Building program", self._build_command)

    def _on_run(self) -> None:
        self._run_action("Running program", self._run_command)

    def _on_test(self) -> None:
        self._run_action("Running tests", self._test_command)

    def _run_action(self, description, command_factory) -> None:
        if self._command_thread:
            messagebox.showinfo(
                "Command running",
                "Wait for the existing command to complete.",
            )
            return

        project_root = self._ensure_project_root()
        if project_root is None:
            return

        command_info = command_factory(project_root)
        if command_info is None:
            return
        command, cwd = command_info

        self.status_var.set(description)
        for btn in self._buttons:
            btn.configure(state=tk.DISABLED)

        self._command_thread = threading.Thread(
            target=self._run_command_thread,
            args=(description, command, cwd),
            daemon=True,
        )
        self._command_thread.start()

    def _run_command_thread(
        self, description: str, command: Sequence[str], cwd: Path
    ) -> None:
        self._queue_log(f"=== {description} ===")
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self._queue_log(line.rstrip())
            return_code = proc.wait()
            self._queue_log(f"[exit code {return_code}]")
        except FileNotFoundError:
            self._queue_log(
                f"Command not found: {command[0]}"
            )
        except Exception as exc:
            self._queue_log(f"Command failed: {exc}")
        finally:
            self.after(0, self._on_command_complete)

    def _on_command_complete(self) -> None:
        self._command_thread = None
        self.status_var.set("Idle")
        self.refresh_project_path()

    def _queue_log(self, message: str) -> None:
        self.after(0, self._append_log, message)

    def _append_log(self, message: str) -> None:
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def _install_command(
        self, project_root: Path
    ) -> tuple[list[str], Path] | None:
        scripts = project_root / "scripts"
        script = None
        if os.name == "nt":
            script = scripts / "install_deps.ps1"
            if not script.exists():
                messagebox.showerror(
                    "Missing script",
                    f"Could not find {script}.",
                )
                return None
            command = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ]
        elif sys.platform == "darwin":
            script = scripts / "install_deps_mac.sh"
            if not script.exists():
                script = scripts / "install_deps.sh"
            if not script.exists():
                messagebox.showerror(
                    "Missing script",
                    "No install_deps script found.",
                )
                return None
            command = ["/bin/bash", str(script)]
        else:
            script = scripts / "install_deps.sh"
            if not script.exists():
                messagebox.showerror(
                    "Missing script",
                    f"Could not find {script}.",
                )
                return None
            command = ["/bin/bash", str(script)]
        return command, project_root

    def _build_command(
        self, project_root: Path
    ) -> tuple[list[str], Path] | None:
        scripts = project_root / "scripts"
        if os.name == "nt":
            script = scripts / "build.bat"
            if not script.exists():
                messagebox.showerror("Missing script", f"{script} not found.")
                return None
            return (["cmd", "/c", str(script)], project_root)
        script = scripts / "build.sh"
        if not script.exists():
            messagebox.showerror("Missing script", f"{script} not found.")
            return None
        return (["/bin/bash", str(script)], project_root)

    def _run_command(
        self, project_root: Path
    ) -> tuple[list[str], Path] | None:
        scripts = project_root / "scripts"
        if os.name == "nt":
            script = scripts / "run.bat"
            if not script.exists():
                messagebox.showerror("Missing script", f"{script} not found.")
                return None
            return (["cmd", "/c", str(script)], project_root)
        script = scripts / "run.sh"
        if not script.exists():
            messagebox.showerror("Missing script", f"{script} not found.")
            return None
        return (["/bin/bash", str(script)], project_root)

    def _test_command(
        self, project_root: Path
    ) -> tuple[list[str], Path] | None:
        build_dir = project_root / "build"
        if not build_dir.exists():
            messagebox.showerror(
                "Build directory missing",
                f"{build_dir} not found. Run build first.",
            )
            return None
        command = ["ctest", "--output-on-failure"]
        return command, build_dir


class GeneratorGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GPU Compress Project Generator (Tkinter GUI)")
        self.geometry("1000x600")

        self.base_dir = tk.StringVar(value=str(Path.cwd()))
        self.project_root: Path | None = None
        self.launcher: WelcomeLauncher | None = None

        self._build_widgets()

    def _build_widgets(self):
        top_frame = ttk.Frame(self)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        ttk.Label(top_frame, text="Base folder:").pack(side=tk.LEFT)
        entry = ttk.Entry(top_frame, textvariable=self.base_dir, width=60)
        entry.pack(side=tk.LEFT, padx=4)

        ttk.Button(
            top_frame, text="Browse...",
            command=self._on_browse
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            top_frame, text="Generate Project",
            command=self._on_generate
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            top_frame, text="Welcome Launcher",
            command=self._open_launcher
        ).pack(side=tk.LEFT, padx=4)

        # Split: left = file tree, right = log
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Treeview
        tree_frame = ttk.Frame(paned)
        self.tree = ttk.Treeview(tree_frame, columns=("path",), show="tree")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        paned.add(tree_frame, weight=3)

        # Log
        log_frame = ttk.Frame(paned)
        self.log_text = tk.Text(log_frame, wrap=tk.NONE, height=10)
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_vsb.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        paned.add(log_frame, weight=2)

    def log(self, msg: str):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.update_idletasks()

    def _on_browse(self):
        path = filedialog.askdirectory(
            title="Choose base folder for project",
            initialdir=self.base_dir.get()
        )
        if path:
            self.base_dir.set(path)

    def _on_generate(self):
        base = Path(self.base_dir.get()).expanduser().resolve()
        if not base.exists():
            messagebox.showerror("Error", f"Base folder does not exist:\n{base}")
            return

        try:
            project_root = generate_project(base, self.log)
            self.project_root = project_root
            self._populate_tree(project_root)
            self._notify_launcher()
            messagebox.showinfo("Done", f"Project generated at:\n{project_root}")
        except Exception as exc:
            messagebox.showerror("Error", f"Generation failed:\n{exc}")

    def _populate_tree(self, root: Path):
        # Clear previous
        for item in self.tree.get_children():
            self.tree.delete(item)

        def insert_node(parent, path: Path):
            node_id = self.tree.insert(
                parent, "end", text=path.name or str(path), open=True
            )
            if path.is_dir():
                for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                    insert_node(node_id, child)

        insert_node("", root)

    def _open_launcher(self):
        if self.launcher:
            self.launcher.lift()
            return

        def on_close():
            self.launcher = None

        self.launcher = WelcomeLauncher(self, self._get_project_root, on_close)

    def _get_project_root(self) -> Path | None:
        return self.project_root

    def _notify_launcher(self) -> None:
        if self.launcher:
            self.launcher.refresh_project_path()


if __name__ == "__main__":
    app = GeneratorGUI()
    app.mainloop()
