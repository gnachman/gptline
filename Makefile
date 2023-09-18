.PHONY: test upload

run:
	source testenv/bin/activate ; pip install -e . ; testenv/bin/gptline

rebuild:
	rm -rf testenv/ ; python3 -m venv testenv ; source testenv/bin/activate ; pip install -e . ; testenv/bin/gptline

upload:
	rm -f dist/*
	python3 setup.py bdist_wheel
	python3 setup.py sdist
	twine upload dist/*
