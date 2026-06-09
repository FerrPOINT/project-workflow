"""Tests for hello_world module."""

import pytest

from hello_world import hello


def test_hello_default():
    """Test hello with default name."""
    assert hello() == "Hello, World!"


def test_hello_custom():
    """Test hello with custom name."""
    assert hello("Alice") == "Hello, Alice!"


def test_hello_empty():
    """Test hello with empty name."""
    assert hello("") == "Hello, !"
