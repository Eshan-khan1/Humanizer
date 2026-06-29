#!/usr/bin/env python3
"""Wrapper — runs Generate tone data.py in the project root."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent.parent / "Generate tone data.py"), run_name="__main__")
