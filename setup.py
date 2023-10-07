from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="gptline",
    version="1.0.7",
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "gptline = src.main:main"
        ]
    },
)
