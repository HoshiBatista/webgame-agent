"""Test public player code inside the OS sandbox, with no repository secrets or database."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import pytest

    from validation import native

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["chromium", "all"], default="all")
    parser.add_argument("--output", type=Path, default=ROOT / ".data/runtime-browser.xml")
    args = parser.parse_args()
    browser = native.browser_path()
    packages = Path(pytest.__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="gf-runtime-tests-") as directory:
        scratch = Path(directory).resolve()
        source = scratch / "source"
        source.mkdir()
        # Only public Python/JS/CSS sources, never .env, .git, diagnostics or the app DB.
        for name in ("generation", "validation"):
            for path in (ROOT / name).rglob("*"):
                if path.is_file() and path.suffix in {".py", ".js", ".css"}:
                    target = source / path.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
        # The controller imports this inert, public helper; no Django settings are copied.
        public_app = source / "gameforge"
        public_app.mkdir()
        (public_app / "__init__.py").touch()
        shutil.copyfile(ROOT / "gameforge" / "telemetry.py", public_app / "telemetry.py")
        tests = source / "tests"
        tests.mkdir()
        (tests / "__init__.py").touch()
        for name in ("test_experience.py", "test_preview_audio.py", "test_compact_generation.py"):
            shutil.copyfile(ROOT / "tests" / name, tests / name)
        (scratch / "pytest.ini").write_text(
            "[pytest]\nmarkers =\n browser: isolated browser\n runtime_browser: public runtime\n native_browser: OS sandbox\n"
        )
        entry = scratch / "entry.py"
        entry.write_text(
            "import sys\n"
            f"sys.path[:0] = {[str(source), str(packages)]!r}\n"
            "import pytest\n"
            f"raise SystemExit(pytest.main({['-c', str(scratch / 'pytest.ini'), '-p', 'no:cacheprovider', '-m', 'runtime_browser', str(tests / 'test_experience.py'), str(tests / 'test_preview_audio.py'), '--junitxml', str(scratch / 'report.xml'), '-v']!r}))\n"
        )
        reads = [*native.runtime_paths(browser), str(packages), str(native.BROWSERS.resolve())]
        env = {"PATH": "/usr/bin:/bin", "HOME": str(scratch), "TMPDIR": str(scratch),
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "GAMEFORGE_RUNTIME_SANDBOX": "1", "GAMEFORGE_RUNTIME_ENGINE": args.engine,
               "CHROMIUM_EXECUTABLE": str(browser), "PLAYWRIGHT_BROWSERS_PATH": str(native.BROWSERS.resolve())}
        if sys.platform == "linux":
            (scratch / "alsa.conf").write_text("pcm.!default { type null }\n")
            env.update(ALSA_CONFIG_PATH=str(scratch / "alsa.conf"), DBUS_SESSION_BUS_ADDRESS="unix:path=/dev/null")
            # WebKit's real Web Audio pipeline uses a clocked virtual GStreamer sink.
            env.update(GST_PLUGIN_FEATURE_RANK="fakeaudiosink:MAX", WEBKIT_GST_MAX_NUMBER_OF_AUDIO_OUTPUT_CHANNELS="2")
            if native.LINUX_LIBRARIES.is_dir():
                env["LD_LIBRARY_PATH"] = str(native.LINUX_LIBRARIES.resolve())
                plugins = native.LINUX_LIBRARIES / "gstreamer-1.0"
                if plugins.is_dir():
                    env["GST_PLUGIN_PATH_1_0"] = str(plugins.resolve())
        command = native.sandbox_command(reads, scratch, [str(Path(sys.executable).resolve()), "-I", "-S", str(entry)])
        result = subprocess.run(command, cwd=scratch, env=env, timeout=240)
        if (scratch / "report.xml").is_file():
            args.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(scratch / "report.xml", args.output)
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
