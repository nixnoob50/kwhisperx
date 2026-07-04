"""Regression tests for single-instance lock (v0.2.3)."""

from __future__ import annotations

import pytest

from kwhisperx import single_instance


@pytest.fixture(autouse=True)
def reset_lock():
    single_instance.release()
    yield
    single_instance.release()


class TestSingleInstance:
    def test_acquire_and_release(self, tmp_path, monkeypatch) -> None:
        lock_dir = tmp_path / "config"
        lock_dir.mkdir()
        monkeypatch.setattr("kwhisperx.single_instance.CONFIG_DIR", lock_dir)

        assert single_instance.acquire() is True
        single_instance.release()
        assert single_instance.acquire() is True

    def test_second_acquire_without_release_fails(self, tmp_path, monkeypatch) -> None:
        lock_dir = tmp_path / "config"
        lock_dir.mkdir()
        monkeypatch.setattr("kwhisperx.single_instance.CONFIG_DIR", lock_dir)

        assert single_instance.acquire() is True
        assert single_instance.acquire() is False
        single_instance.release()
