.PHONY: update restart logs status

# Обновление проекта (git pull + requirements + restart)
update:
	@echo "Updating Life Analytics..."
	git pull origin master
	cd backend && source venv/bin/activate && pip install -r requirements.txt
	systemctl restart life-analytics
	@echo "✓ Updated and restarted!"

# Перезапуск backend
restart:
	systemctl restart life-analytics
	@echo "✓ Backend restarted!"

# Просмотр логов
logs:
	journalctl -u life-analytics -f

# Статус сервиса
status:
	systemctl status life-analytics

# Проверка nginx
nginx-test:
	nginx -t

# Перезапуск nginx
nginx-restart:
	systemctl restart nginx
	@echo "✓ Nginx restarted!"
