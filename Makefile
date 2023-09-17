.PHONY: test upload

test:
	rm -rf testenv/ ; python3 -m venv testenv ; source testenv/bin/activate.csh ; pip install -e . ; rehash ; gptline

upload:
	rm -f dist/*
	python3 setup.py bdist_wheel
	python3 setup.py sdist
	twine upload dist/*
