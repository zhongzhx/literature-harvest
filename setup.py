"""Backward-compatible setup.py.

Modern installs use pyproject.toml, but older pip versions
fall back to this file.
"""
from setuptools import find_packages, setup

setup(
    name="literature-harvest",
    version="0.2.0",
    description="Scholarly literature harvesting with institutional access support",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/zhongzhx/literature-harvest",
    packages=find_packages(exclude=["tests"]),
    python_requires=">=3.10",
    install_requires=[
        "requests>=2.28",
        "pandas>=1.5",
        "beautifulsoup4>=4.12",
        "lxml>=4.9",
    ],
    extras_require={
        "browser": ["playwright>=1.40"],
        "test": ["pytest>=7"],
    },
    entry_points={
        "console_scripts": [
            "literature-harvest=literature_harvest.cli:main",
        ],
    },
)
