# ==============================================================================
# VisionAttend - common development tasks
# ==============================================================================

.PHONY: help install run test coverage lint e2e accuracy loadtest clean docker-build docker-up docker-down k8s-apply k8s-delete

help:
	@echo "Available commands:"
	@echo "  make install       Install dependencies (CPU PyTorch + dev requirements)"
	@echo "  make run           Run application locally with Gunicorn (or Flask dev)"
	@echo "  make test          Run the automated pytest suite"
	@echo "  make coverage      Run pytest with terminal code coverage report"
	@echo "  make lint          Run ruff and bandit"
	@echo "  make e2e           Run end-to-end tests against the running Docker stack"
	@echo "  make accuracy      Measure recognition accuracy on LFW (downloads ~180 MB once)"
	@echo "  make loadtest      Load-test the kiosk endpoint on the running Docker stack"
	@echo "  make clean         Remove build, cache, and bytecode artifacts"
	@echo "  make docker-build  Build the Docker image"
	@echo "  make docker-up     Start full stack (App + PostgreSQL + Redis + Prometheus)"
	@echo "  make docker-down   Stop and tear down Docker stack"
	@echo "  make k8s-apply     Deploy manifests to Kubernetes cluster"
	@echo "  make k8s-delete    Delete Kubernetes deployments"

install:
	pip install --upgrade pip
	pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
	pip install -r requirements-dev.txt

run:
	python run.py

test:
	pytest -v

coverage:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check .
	bandit -r app/ -ll

e2e:
	pytest -m e2e tests/e2e

accuracy:
	python scripts/evaluate_accuracy.py

loadtest:
	python scripts/load_test.py

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
