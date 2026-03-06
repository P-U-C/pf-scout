"""pf-scout package setup."""

from setuptools import setup, find_packages

setup(
    name="pf-scout",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.0",
        "pyyaml>=6.0",
        "requests>=2.28",
    ],
    entry_points={
        "console_scripts": [
            "pf-scout=pf_scout.cli:main",
        ],
    },
    python_requires=">=3.9",
    description="Contact intelligence for Post Fiat contributor recruitment",
)
