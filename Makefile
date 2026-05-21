.PHONY: run test lint

run:
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -q
