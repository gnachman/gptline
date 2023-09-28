from setuptools import setup

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="gptline",
    version="1.0.5",
    packages=["src"],
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "gptline = src.main:main"
        ]
    },
)
