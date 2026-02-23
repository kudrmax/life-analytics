# Деплой Life Analytics на VPS

## Информация о сервере

- **IP:** 77.222.35.163
- **Username:** root
- **SSH ключ:** ~/.ssh/vps_key
- **Репозиторий:** https://github.com/kudrmax/life-analytics.git

---

## Деплой (делается один раз)

### 1. Подключиться к серверу

```bash
ssh -i ~/.ssh/vps_key root@77.222.35.163
```

### 2. Установить необходимое ПО

```bash
apt update
apt install -y python3 python3-pip python3-venv nginx git make
```

### 3. Склонировать проект

```bash
cd /var/www
git clone https://github.com/kudrmax/life-analytics.git
cd life-analytics
```

### 4. Настроить backend

```bash
cd /var/www/life-analytics/backend

# Создать виртуальное окружение
python3 -m venv venv

# Активировать
source venv/bin/activate

# Установить зависимости
pip install -r requirements.txt
```

### 5. Создать секретный ключ для production

```bash
# Сгенерировать случайный ключ
python3 -c 'import secrets; print("LA_SECRET_KEY=" + secrets.token_urlsafe(32))' >> /etc/environment

# Перезагрузить переменные окружения
source /etc/environment
```

**Зачем:** Ваши JWT токены подписываются этим ключом. Без уникального ключа кто угодно может подделать токены.

### 6. Создать systemd сервис (автозапуск backend)

```bash
nano /etc/systemd/system/life-analytics.service
```

Вставить:

```ini
[Unit]
Description=Life Analytics Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/life-analytics/backend
Environment="PATH=/var/www/life-analytics/backend/venv/bin"
EnvironmentFile=/etc/environment
ExecStart=/var/www/life-analytics/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Сохранить: `Ctrl+O`, `Enter`, `Ctrl+X`

**Зачем:** Чтобы backend работал постоянно в фоне и автоматически запускался после перезагрузки сервера.

Запустить сервис:

```bash
systemctl daemon-reload
systemctl enable life-analytics
systemctl start life-analytics

# Проверить что работает
systemctl status life-analytics
```

### 7. Настроить nginx

```bash
nano /etc/nginx/sites-available/life-analytics
```

Вставить:

```nginx
server {
    listen 80;
    server_name 77.222.35.163;

    # Frontend (статические файлы)
    location / {
        root /var/www/life-analytics/frontend;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API docs
    location /docs {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

Сохранить и активировать:

```bash
ln -s /etc/nginx/sites-available/life-analytics /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
```

**Зачем:** nginx раздаёт ваши HTML/CSS/JS файлы и перенаправляет запросы к `/api/` на ваш FastAPI backend.

### 8. Готово!

Откройте в браузере: **http://77.222.35.163**

---

## Обновление проекта (когда выходит новая версия)

**На локальной машине** - запушить изменения:

```bash
git add .
git commit -m "Update"
git push origin master
```

**На сервере** - обновить одной командой:

```bash
ssh -i ~/.ssh/vps_key root@77.222.35.163 "cd /var/www/life-analytics && make update"
```

**Или** подключиться к серверу и запустить:

```bash
ssh -i ~/.ssh/vps_key root@77.222.35.163
cd /var/www/life-analytics
make update
```

Эта команда автоматически:
- Подтянет изменения из git (`git pull`)
- Обновит Python зависимости (`pip install -r requirements.txt`)
- Перезапустит backend (`systemctl restart`)

### Другие полезные make команды

```bash
make restart        # Просто перезапустить backend
make logs          # Посмотреть логи в реальном времени
make status        # Проверить статус сервиса
make nginx-restart # Перезапустить nginx
```

---

## Полезные команды

**С использованием Makefile** (из директории `/var/www/life-analytics`):

```bash
make update         # Обновить проект (git pull + pip install + restart)
make restart        # Перезапустить backend
make logs          # Посмотреть логи backend
make status        # Статус backend
make nginx-restart # Перезапустить nginx
```

**Прямые команды systemd:**

```bash
systemctl status life-analytics      # Проверить статус
systemctl restart life-analytics     # Перезапустить backend
journalctl -u life-analytics -f      # Логи в реальном времени
tail -f /var/log/nginx/error.log    # Логи nginx
```

---

## Если что-то не работает

**Backend не запускается:**
```bash
journalctl -u life-analytics -n 50
```

**Nginx показывает ошибку:**
```bash
tail -f /var/log/nginx/error.log
```

**502 Bad Gateway:**
- Проверьте что backend запущен: `systemctl status life-analytics`
