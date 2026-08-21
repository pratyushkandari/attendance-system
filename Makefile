# ==============================================================================
# Attendance System - Engineering Automation Makefile
# ==============================================================================

.PHONY: help install run test coverage lint clean docker-build docker-up docker-down k8s-apply k8s-delete

help:
	@echo "Available commands:"
	@echo "  make install       Install project dependencies into virtual environment"
	@echo "  make run           Run application locally with Gunicorn (or Flask dev)"
	@echo "  make test          Run 28-test automated pytest suite"
	@echo "  make coverage      Run pytest with terminal code coverage report"
	@echo "  make lint          Run ruff and bandit security analysis"
	@echo "  make clean         Remove build, cache, and bytecode artifacts"
	@echo "  make docker-build  Build production multi-stage Docker micro-container"
	@echo "  make docker-up     Start full stack (App + PostgreSQL + Redis + Prometheus)"
	@echo "  make docker-down   Stop and tear down Docker stack"
	@echo "  make k8s-apply     Deploy manifests to Kubernetes cluster"
	@echo "  make k8s-delete    Delete Kubernetes deployments"

install:
	pip install --upgrade pip
	pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
	pip install -r requirements.txt

run:
	python run.py

test:
	pytest -v

coverage:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check .
	bandit -r app/ -ll

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	rm -rf .coverage htmlcov dist build *.egg-info

docker-build:
	docker build -t attendance-system:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

k8s-apply:
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/deployment.yaml
	kubectl apply -f k8s/service.yaml
	kubectl apply -f k8s/hpa.yaml

k8s-delete:
	kubectl delete -f k8s/hpa.yaml
	kubectl delete -f k8s/service.yaml
	kubectl delete -f k8s/deployment.yaml
	kubectl delete -f k8s/configmap.yaml
