SHELL := /bin/bash

.PHONY: help up build-up down delete reset logs logs-backend venv ensure-db test test-unit test-int test-user migrate restart update status backup-up backup-down backup-logs backup-now backup-restore deploy prod-logs prod-status prod-db lint-js setup

.DEFAULT_GOAL := help

# ─── Help ───

help: ## Показать эту справку
	@echo ""
	@echo "  Life Analytics — доступные команды:"
	@echo ""
	@echo "  Docker:"
	@echo "    make up              Запустить сервисы (быстро, офлайн)"
	@echo "    make build-up        Пересобрать образы и запустить"
	@echo "    make down            Остановить все сервисы"
	@echo "    make delete          Остановить и удалить всё включая БД"
	@echo "    make reset           Пересоздать с нуля (delete + build-up)"
	@echo "    make logs            Логи всех сервисов"
	@echo "    make logs-backend    Логи только backend"
	@echo "    make status          Статус контейнеров"
	@echo ""
	@echo "  Lint и тесты:"
	@echo "    make venv            Создать/обновить виртуальное окружение"
	@echo "    make lint-js         Проверить синтаксис JS файлов"
	@echo "    make test            Запустить все тесты (БД поднимается автоматически)"
	@echo "    make test-unit       Запустить только unit-тесты"
	@echo "    make test-int        Запустить только интеграционные тесты"
	@echo "    make test-user       Создать тестового пользователя с данными за 15 дней"
	@echo ""
	@echo "  Production (на сервере):"
	@echo "    make update          git pull + пересобрать и перезапустить"
	@echo "    make restart         Перезапустить backend"
	@echo ""
	@echo "  Production (с локальной машины, нужен VPS_HOST):"
	@echo "    make deploy          Ручной деплой на VPS через SSH"
	@echo "    make prod-logs       Логи production через SSH"
	@echo "    make prod-status     Статус контейнеров на production"
	@echo "    make prod-db         Подключиться к production БД"
	@echo ""
	@echo "  Настройка сервера:"
	@echo "    make setup           Настроить файрвол (ufw: SSH + frontend)"
	@echo ""
	@echo "  Backup (нужен YADISK_TOKEN в .env):"
	@echo "    make backup-up       Запустить сервис бэкапов"
	@echo "    make backup-down     Остановить сервис бэкапов"
	@echo "    make backup-logs     Логи бэкапов"
	@echo "    make backup-now      Сделать бэкап прямо сейчас (разово)"
	@echo "    make backup-restore  Восстановить БД из бэкапа (FILE=path.sql.gz)"
	@echo ""

# ─── Lint ───

lint-js: ## Проверить синтаксис JS файлов
	@if command -v node >/dev/null 2>&1; then \
		echo "Checking JS syntax..."; \
		fail=0; \
		for f in frontend/js/*.js; do \
			node --check "$$f" || fail=1; \
		done; \
		[ $$fail -eq 0 ] && echo "JS syntax OK" || exit 1; \
	else \
		echo "Warning: node not found, skipping JS syntax check"; \
	fi

# ─── Docker ───

define check_backend_health
	@echo "Waiting for backend health check..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		if curl -sf --noproxy localhost http://localhost:8000/api/health > /dev/null 2>&1; then \
			echo "Backend is healthy!"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "ERROR: Backend failed to start!"; \
	docker compose logs --tail=30 backend; \
	exit 1
endef

up: lint-js
	docker compose up -d
	$(check_backend_health)

build-up: lint-js
	docker compose up -d --build
	$(check_backend_health)

down:
	docker compose down

delete: ## Остановить и удалить всё включая БД (volumes)
	docker compose down -v

reset: delete build-up ## Пересоздать всё с нуля (delete + build-up)

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

# ─── Virtual environment ───

backend/venv/bin/activate: backend/pyproject.toml
	python3 -m venv backend/venv
	backend/venv/bin/pip install -e backend
	@touch $@

venv: backend/venv/bin/activate ## Создать/обновить виртуальное окружение

# ─── Тесты ───

ensure-db: ## Поднять контейнер БД если не запущен
	@if pg_isready -h localhost -p 5432 -U la_user > /dev/null 2>&1; then \
		echo "PostgreSQL is ready"; \
	elif docker compose ps db --format '{{.State}}' 2>/dev/null | grep -q running; then \
		echo "Waiting for PostgreSQL..."; \
		for i in 1 2 3 4 5 6 7 8 9 10; do \
			pg_isready -h localhost -p 5432 -U la_user > /dev/null 2>&1 && break; \
			sleep 1; \
		done; \
	else \
		echo "Starting database..."; \
		docker compose up -d db; \
		echo "Waiting for PostgreSQL..."; \
		for i in 1 2 3 4 5 6 7 8 9 10; do \
			docker compose exec db pg_isready -U la_user -d life_analytics > /dev/null 2>&1 && break; \
			sleep 1; \
		done; \
	fi

test: venv ensure-db ## Запустить все тесты
	cd backend && source venv/bin/activate && python -m pytest -n auto $(ARGS)

test-unit: venv ## Запустить только unit-тесты
	cd backend && source venv/bin/activate && python -m pytest tests/ -k "unit" $(ARGS)

test-int: venv ensure-db ## Запустить только интеграционные (API) тесты
	cd backend && source venv/bin/activate && python -m pytest tests/ -k "not unit" -n auto $(ARGS)

test-user: ## Создать тестового пользователя с данными за 15 дней
	python3 scripts/seed_test_user.py
	@echo ""
	@echo "  Логин: testtest"
	@echo "  Пароль: testtest"
	@echo ""

# ─── Production ───

update: lint-js
	@echo "Updating Life Analytics..."
	git pull origin master
	docker compose up -d --build
	@echo "Updated and restarted!"

restart:
	docker compose restart backend
	@echo "Backend restarted!"

status:
	docker compose ps

# ─── Remote (с локальной машины) ───

deploy:
	@test -n "$$VPS_HOST" || (echo "Error: VPS_HOST not set. Usage: VPS_HOST=1.2.3.4 make deploy" && exit 1)
	ssh root@$${VPS_HOST} "cd /opt/life-analytics && git pull origin master && docker compose up -d --build --remove-orphans && docker image prune -f"

prod-logs:
	@test -n "$$VPS_HOST" || (echo "Error: VPS_HOST not set." && exit 1)
	ssh root@$${VPS_HOST} "cd /opt/life-analytics && docker compose logs -f --tail=100"

prod-status:
	@test -n "$$VPS_HOST" || (echo "Error: VPS_HOST not set." && exit 1)
	ssh root@$${VPS_HOST} "cd /opt/life-analytics && docker compose ps"

prod-db:
	@test -n "$$VPS_HOST" || (echo "Error: VPS_HOST not set." && exit 1)
	ssh -t root@$${VPS_HOST} "docker exec -it life-analytics-db-1 psql -U la_user -d life_analytics"

# ─── Server setup ───

setup: ## Настроить файрвол (ufw: разрешить SSH + frontend)
	@echo "Настраиваю файрвол..."
	ufw default deny incoming
	ufw default allow outgoing
	ufw allow 22/tcp
	ufw allow 3000/tcp
	ufw --force enable
	ufw status verbose
	@echo "Файрвол настроен!"

# ─── Backup ───

backup-up:
	docker compose --profile backup up -d --build backup

backup-down:
	docker compose --profile backup stop backup

backup-logs:
	docker compose --profile backup logs -f backup

backup-now:
	docker compose --profile backup run --rm backup python -c \
		"from backup import run_backup_cycle; run_backup_cycle()"

backup-restore:
	@test -n "$(FILE)" || (echo "Ошибка: укажите FILE. Пример: make backup-restore FILE=backups/file.sql.gz" && echo "" && echo "Доступные бэкапы:" && ls -lh backups/*.sql.gz 2>/dev/null || echo "  (папка backups/ пуста)" && exit 1)
	@test -f "$(FILE)" || (echo "Ошибка: файл $(FILE) не найден" && exit 1)
	@echo "⚠ ВНИМАНИЕ: база life_analytics будет пересоздана из бэкапа $(FILE)"
	@read -p "Продолжить? (y/N) " confirm && [ "$$confirm" = "y" ] || (echo "Отменено." && exit 1)
	@echo "Останавливаю backend..."
	docker compose stop backend
	@echo "Пересоздаю базу..."
	docker exec life-analytics-db-1 psql -U la_user -d postgres -c "DROP DATABASE life_analytics;" -c "CREATE DATABASE life_analytics;"
	@echo "Восстанавливаю из $(FILE)..."
	gunzip -c $(FILE) | docker exec -i life-analytics-db-1 psql -U la_user -d life_analytics
	@echo "Запускаю backend..."
	docker compose start backend
	@echo "Готово! БД восстановлена из $(FILE)"
