# ==============================================================================
# nautilus-lab Makefile
# ==============================================================================
# Research-first trading robots on NautilusTrader
# ==============================================================================

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ------------------------------------------------------------------------------
# Configurable Variables
# ------------------------------------------------------------------------------
UV          ?= uv
RUN         ?= $(UV) run
PYTHON      ?= $(RUN) python
LAB         ?= $(RUN) lab

# Default parameters for CLI commands
ROBOT       ?= regime
FOLDS       ?= 4
BARS        ?= 3000
SYMBOLS     ?= ETHUSDT,BTCUSDT
SYMBOL      ?= ETHUSDT
INTERVAL    ?= 1h
TRIALS      ?= 20
PBO_BLOCKS  ?= 8
CATALOG     ?= catalog
TEARSHEET   ?= reports/tearsheet.html
LIVE_TICKS  ?= 20

# ------------------------------------------------------------------------------
# Help
# ------------------------------------------------------------------------------
.PHONY: help
help: ## Показати це повідомлення з довідкою по всіх командах
	@echo ""
	@echo "Nautilus Lab — Корисні команди для розробки та досліджень"
	@echo "=========================================================="
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Змінні конфігурації (можна перевизначати, напр. make research ROBOT=ema FOLDS=6):"
	@echo "  ROBOT=$(ROBOT)  FOLDS=$(FOLDS)  BARS=$(BARS)  SYMBOLS=$(SYMBOLS)  CATALOG=$(CATALOG)"
	@echo ""

# ------------------------------------------------------------------------------
# Оточення та Залежності
# ------------------------------------------------------------------------------
.PHONY: env-init env-check install install-all install-dev install-api install-ml

env-init: ## Створити .env з .env.example, якщо файл ще не існує
	@test -f .env || cp .env.example .env
	@echo "Файл .env ініціалізовано."

env-check: ## Перевірити налаштування середовища та конфігурацію Settings
	@$(PYTHON) -c "from nautilus_lab.infrastructure.settings import Settings; s=Settings(); print(f'mode={s.trading_mode} robot={s.robot} interval={s.bar_interval} fees={s.fee_schedule()}')"

install: install-dev ## Встановити базові залежності та dev-пакети (pytest, ruff, mypy)

install-dev: ## Встановити dev-залежності через uv
	$(UV) sync

install-api: ## Встановити залежності для FastAPI дашборду (uvicorn, fastapi, websockets)
	$(UV) sync --extra api

install-ml: ## Встановити залежності для ML та досліджень (lightgbm, optuna, arch, polars)
	$(UV) sync --extra ml --extra research

install-all: ## Встановити всі екстри (dev, api, ml, research, alerts, visualization)
	$(UV) sync --extra api --extra ml --extra research --extra alerts --extra visualization

# ------------------------------------------------------------------------------
# Контроль Якості та Тести
# ------------------------------------------------------------------------------
.PHONY: test test-unit test-integration test-cov coverage lint lint-fix format format-check typecheck mypy check ci

lint: ## Запустити лінтер ruff check
	$(RUN) ruff check

lint-fix: ## Автоматично виправити помилки лінтера ruff
	$(RUN) ruff check --fix

format: ## Форматувати код за допомогою ruff format
	$(RUN) ruff format

format-check: ## Перевірити форматування коду без змін
	$(RUN) ruff format --check

typecheck: ## Перевірити статичну типізацію через mypy (strict)
	$(RUN) mypy src tests

mypy: typecheck

test: ## Запустити всі тести
	$(RUN) pytest

test-unit: ## Запустити швидкі юніт-тести
	$(RUN) pytest tests/unit -q

test-integration: ## Запустити інтеграційні тести
	$(RUN) pytest tests/integration -q

test-cov: ## Запустити тести з перевіркою покриття (поріг 80%)
	$(RUN) pytest --cov --cov-report=term-missing

coverage: test-cov

check: lint format-check typecheck spec-check test ## Комплексна перевірка якості (lint, format, types, specs, tests)

ci: lint format-check typecheck spec-check test smoke notebook-check test-cov ## Повне відтворення GitHub Actions CI пайплайну

# ------------------------------------------------------------------------------
# Специфікації (Spec-Driven Development)
# ------------------------------------------------------------------------------
.PHONY: spec-check spec-validate spec-test

spec-check: ## Перевірити відповідність усіх YAML-специфікацій коду
	$(PYTHON) specs/_validator.py

spec-validate: ## Перевірити специфікацію конкретного робота (напр. make spec-validate ROBOT=regime)
	$(PYTHON) specs/_validator.py $(ROBOT)

spec-test: ## Запустити тести специфікацій через pytest
	$(RUN) pytest tests/unit/test_specs.py -q

# ------------------------------------------------------------------------------
# Дослідження та Бектести (Research & Walk-Forward)
# ------------------------------------------------------------------------------
.PHONY: smoke research research-ema research-regime research-pairs research-folds research-pbo research-optuna research-full research-tearsheet xsmom propose propose-dry

smoke: ## Швидкий smoke-тест бектесту на синтетичних даних без мережі
	$(LAB) research --synthetic --bars $(BARS)

research: ## Запустити walk-forward дослідження за замовчуванням по каталогу
	$(LAB) research --robot $(ROBOT)

research-ema: ## Запустити дослідження базового еталону EMA (baseline)
	$(LAB) research --robot ema

research-regime: ## Запустити walk-forward дослідження робота regime з фолдами
	$(LAB) research --robot regime --folds $(FOLDS)

research-pairs: ## Запустити дослідження парного трейдингу (ETH/BTC)
	$(LAB) research --robot pairs

research-folds: ## Запустити walk-forward дослідження заданого робота з N фолдами
	$(LAB) research --robot $(ROBOT) --folds $(FOLDS)

research-pbo: ## Запустити аудит перенавчання PBO / CSCV
	$(LAB) research --robot $(ROBOT) --pbo --pbo-blocks $(PBO_BLOCKS)

research-optuna: ## Запустити байєсівський підбір параметрів через Optuna (extra research)
	$(LAB) research --robot $(ROBOT) --optuna --trials $(TRIALS)

research-full: ## Запустити повний прогін на всій вибірці (full-sample, in-sample only)
	$(LAB) research --robot $(ROBOT) --full-sample

research-tearsheet: ## Згенерувати HTML-тиршит результатів OOS
	@mkdir -p $(dir $(TEARSHEET))
	$(LAB) research --robot $(ROBOT) --tearsheet $(TEARSHEET)

xsmom: ## Запустити дослідження крос-секційного моментуму (кошик активів)
	$(LAB) xsmom --symbols $(SYMBOLS) --folds $(FOLDS) --pbo

propose-dry: ## Переглянути сформований промпт для генерації гіпотез альф без виклику LLM
	$(LAB) propose --dry-run

propose: ## Згенерувати нові гіпотези альф через LLM (офлайн-контур)
	$(LAB) propose

# ------------------------------------------------------------------------------
# Завантаження Даних (Ingest)
# ------------------------------------------------------------------------------
.PHONY: ingest ingest-incremental ingest-funding ingest-trades ingest-live-ticks ingest-depth

ingest: ## Завантажити історичні klines Binance у Parquet-каталог
	$(LAB) ingest --symbols $(SYMBOLS) --catalog $(CATALOG)

ingest-incremental: ## Долити лише нові бари після останнього збереженого
	$(LAB) ingest --incremental --symbols $(SYMBOLS) --catalog $(CATALOG)

ingest-funding: ## Завантажити історію ставок фінансування USD-M
	$(LAB) ingest --funding --symbols $(SYMBOLS) --catalog $(CATALOG)

ingest-trades: ## Завантажити агреговані угоди (тіки для VPIN/Хоукса)
	$(LAB) ingest --trades --symbols $(SYMBOLS) --catalog $(CATALOG)

ingest-live-ticks: ## Збирати живі тіки через WebSocket (LIVE_TICKS=хвилини)
	$(LAB) ingest --trades --live-ticks $(LIVE_TICKS) --symbols $(SYMBOL) --catalog $(CATALOG)

ingest-depth: ## Збирати живі L2-знімки стакану через WebSocket
	$(LAB) ingest --depth --symbols $(SYMBOL) --catalog $(CATALOG)

# ------------------------------------------------------------------------------
# Paper Trading та Аудит
# ------------------------------------------------------------------------------
.PHONY: paper paper-suite paper-report audit-cycle

paper: ## Запустити paper-сесію з веденням журналу
	$(LAB) paper --robot $(ROBOT) --journal

paper-suite: ## Запустити пакет paper-сесій для всіх роботів-кандидатів
	bash scripts/run_paper_suite.sh

paper-report: ## Згенерувати звіт по живих paper-сесіях
	$(PYTHON) scripts/live_paper_report.py

audit-cycle: ## Запустити повний цикл аудиту (4-fold walk-forward для кандидатів)
	bash scripts/run_audit_cycle.sh

# ------------------------------------------------------------------------------
# Machine Learning
# ------------------------------------------------------------------------------
.PHONY: ml-train-meta ml-train-formulaic ml-train-obi

ml-train-meta: ## Навчити модель мета-лейблінгу (LightGBM)
	@mkdir -p models
	$(LAB) ml train --model-type meta_label --output models/meta_label.txt

ml-train-formulaic: ## Навчити формульну модель (LightGBM)
	@mkdir -p models
	$(LAB) ml train --model-type formulaic --output models/formulaic.txt

ml-train-obi: ## Навчити модель OBI (LightGBM)
	@mkdir -p models
	$(LAB) ml train --model-type obi --output models/ml_obi.txt

# ------------------------------------------------------------------------------
# Jupyter Зошити та Звіти
# ------------------------------------------------------------------------------
.PHONY: notebook-gen notebook-check

notebook-gen: ## Згенерувати дослідницький Jupyter-ноутбук
	$(PYTHON) scripts/generate_research_notebook.py

notebook-check: ## Перевірити виконання дослідницького ноутбука
	$(PYTHON) scripts/check_notebook.py

# ------------------------------------------------------------------------------
# API та Frontend
# ------------------------------------------------------------------------------
.PHONY: api frontend-install frontend-dev frontend-build frontend-lint frontend-check

api: ## Запустити бекенд-сервер FastAPI з автоперезавантаженням (порт 8000)
	$(RUN) uvicorn nautilus_lab.api.app:app --host 0.0.0.0 --port 8000 --reload

frontend-install: ## Встановити залежності фронтенду (npm install)
	cd frontend && npm install

frontend-dev: ## Запустити dev-сервер фронтенду (Vite)
	cd frontend && npm run dev

frontend-build: ## Зібрати фронтенд для продакшену
	cd frontend && npm run build

frontend-lint: ## Запустити лінтер фронтенду (oxlint)
	cd frontend && npm run lint

frontend-check: ## Перевірити логіку зв'язку фронтенду та бекенду
	cd frontend && npm run check:logic

# ------------------------------------------------------------------------------
# Docker та VPS Деплой
# ------------------------------------------------------------------------------
.PHONY: docker-build docker-up docker-down docker-logs deploy-vps pull-vps

docker-build: ## Зібрати Docker-образи (deploy/docker-compose.yml)
	docker compose -f deploy/docker-compose.yml build

docker-up: ## Запустити контейнери у фоновому режимі
	docker compose -f deploy/docker-compose.yml up -d

docker-down: ## Зупинити контейнери
	docker compose -f deploy/docker-compose.yml down

docker-logs: ## Переглядати логи контейнерів
	docker compose -f deploy/docker-compose.yml logs -f

deploy-vps: ## Задеплоїти зафіксований код на VPS (потрібно VPS=user@host)
	bash scripts/deploy_vps.sh

pull-vps: ## Синхронізувати логи/дані/каталог з VPS (потрібно VPS=user@host)
	bash scripts/pull_vps.sh

# ------------------------------------------------------------------------------
# Очищення
# ------------------------------------------------------------------------------
.PHONY: clean clean-all

clean: ## Очистити тимчасові файли кешу (.pytest_cache, .ruff_cache, .mypy_cache, pycache)
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

clean-all: clean ## Повне очищення кешу та згенерованих звітів
	rm -rf reports/tearsheet.html reports/paper/*.txt reports/audit/*.txt
