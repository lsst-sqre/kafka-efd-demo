.PHONY: help installapp test image travis-docker-deploy version

VERSION=$(shell kafkaefd --version)

help:
	@echo "Make command reference"
	@echo "  make installapp .. (install app for development)"
	@echo "  make test ........ (run unit tests pytest)"
	@echo "  make image ....... (make tagged Docker image)"
	@echo "  make travis-docker-deploy (push image to Docker Hub from Travis CI)"
	@echo "  make version ..... (print the app version)"

installapp:
	pip install -e ".[dev]"

test:
	pytest

image:
	python setup.py sdist
	docker build --build-arg VERSION=$(VERSION) -t lsstsqre/kafka-efd-demo:build .

travis-docker-deploy:
	./bin/travis-docker-deploy.bash lsstsqre/kafka-efd-demo build

version:
	kafkaefd --version
