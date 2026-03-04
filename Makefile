SHELL := /bin/bash

.PHONY: help up down logs logs-backend migrate restart update status nginx-test nginx-restart backup-up backup-down backup-logs backup-now

.DEFAULT_GOAL := help

# ─── Help ───

help: ## Показать эту справку
	@echo ""
	@echo "  Life Analytics — доступные команды:"
	@echo ""
	@echo "  Docker:"
	@echo "    make up              Запустить все сервисы (build + detached)"
	@echo "    make down            Остановить все сервисы"
	@echo "    make logs            Логи всех сервисов"
	@echo "    make logs-backend    Логи только backend"
	@echo "    make status          Статус контейнеров"
	@echo ""
	@echo "  Production:"
	@echo "    make update          git pull + пересобрать и перезапустить"
	@echo "    make restart         Перезапустить backend"
	@echo "    make nginx-test      Проверить конфиг nginx"
	@echo "    make nginx-restart   Перезапустить nginx"
	@echo ""
	@echo "  Backup (нужен YADISK_TOKEN в .env):"
	@echo "    make backup-up       Запустить сервис бэкапов"
	@echo "    make backup-down     Остановить сервис бэкапов"
	@echo "    make backup-logs     Логи бэкапов"
	@echo "    make backup-now      Сделать бэкап прямо сейчас (разово)"
	@echo ""

# ─── Docker ───

up:
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

nginx-test:
	nginx -t

nginx-restart:
	systemctl restart nginx
	@echo "Nginx restarted!"

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
