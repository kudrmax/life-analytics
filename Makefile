SHELL := /bin/bash

.PHONY: up down logs logs-backend migrate restart update status nginx-test nginx-restart backup-up backup-down backup-logs backup-now

# ─── Docker ───

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

# ─── Production (systemd) ───

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
