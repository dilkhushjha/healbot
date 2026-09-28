"""
setup.py — healbot-sdk installable package.

Install with full absolute path to avoid Windows path issues:
    pip install -e "C:\\full\\path\\to\\backend\\sdk"

Or skip pip install entirely — set HEALBOT_SDK_PATH env var instead.
"""

from setuptools import setup, find_packages

setup(
    name="healbot-sdk",
    version="1.0.0",
    description="Universal plug-n-play self-healing adapter for any test framework",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "selenium>=4.0.0",
    ],
    extras_require={
        "playwright": ["playwright>=1.40.0"],
        "robot":      ["robotframework>=6.0", "robotframework-seleniumlibrary>=6.0"],
    },
    entry_points={
        "console_scripts": [
            "healbot=healbot.__main__:main",
        ],
    },
)
