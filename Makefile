SHELL := /bin/bash

.PHONY: help up build-up down logs logs-backend migrate restart update status backup-up backup-down backup-logs backup-now backup-restore deploy ssh prod-logs prod-status prod-db

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
	@echo "    make logs            Логи всех сервисов"
	@echo "    make logs-backend    Логи только backend"
	@echo "    make status          Статус контейнеров"
	@echo ""
	@echo "  Production (на сервере):"
	@echo "    make update          git pull + пересобрать и перезапустить"
	@echo "    make restart         Перезапустить backend"
	@echo ""
	@echo "  Production (с локальной машины, нужен VPS_HOST):"
	@echo "    make deploy          Ручной деплой на VPS через SSH"
	@echo "    make ssh             Подключиться к VPS"
	@echo "    make prod-logs       Логи production через SSH"
	@echo "    make prod-status     Статус контейнеров на production"
	@echo "    make prod-db         Подключиться к production БД"
	@echo ""
	@echo "  Backup (нужен YADISK_TOKEN в .env):"
	@echo "    make backup-up       Запустить сервис бэкапов"
	@echo "    make backup-down     Остановить сервис бэкапов"
	@echo "    make backup-logs     Логи бэкапов"
	@echo "    make backup-now      Сделать бэкап прямо сейчас (разово)"
	@echo "    make backup-restore  Восстановить БД из бэкапа (FILE=path.sql.gz)"
	@echo ""

# ─── Docker ───

up:
	docker compose up -d

build-up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

# ─── Production ───

update:
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

ssh:
	@test -n "$$VPS_HOST" || (echo "Error: VPS_HOST not set. Usage: VPS_HOST=1.2.3.4 make ssh" && exit 1)
	ssh root@$${VPS_HOST}

prod-logs:
	@test -n "$$VPS_HOST" || (echo "Error: VPS_HOST not set." && exit 1)
	ssh root@$${VPS_HOST} "cd /opt/life-analytics && docker compose logs -f --tail=100"

prod-status:
	@test -n "$$VPS_HOST" || (echo "Error: VPS_HOST not set." && exit 1)
	ssh root@$${VPS_HOST} "cd /opt/life-analytics && docker compose ps"

prod-db:
	@test -n "$$VPS_HOST" || (echo "Error: VPS_HOST not set." && exit 1)
	ssh -t root@$${VPS_HOST} "docker exec -it life-analytics-db-1 psql -U la_user -d life_analytics"

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
