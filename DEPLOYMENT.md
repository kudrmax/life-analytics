# Деплой Life Analytics на VPS (Docker Compose)

## Информация о сервере

- **Хостинг:** VDSina
- **ОС:** Ubuntu 22.04+ (или Debian 12+)
- **Репозиторий:** https://github.com/kudrmax/life-analytics.git
- **Расположение на сервере:** `/opt/life-analytics`

---

## Первоначальная настройка VPS (один раз)

### 1. Подключиться к серверу

```bash
ssh root@<IP>
```

### 2. Установить Docker и утилиты

```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
apt install -y make git
```

### 3. Настроить swap (подстраховка для 2 GB RAM)

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### 4. Настроить firewall

```bash
ufw allow 22
ufw allow 80
ufw enable
```

### 5. Склонировать проект

```bash
cd /opt
git clone https://github.com/kudrmax/life-analytics.git
cd life-analytics
```

### 6. Создать .env

```bash
cp .env.example .env
nano .env
```

**Обязательно изменить:**
- `LA_SECRET_KEY` — сгенерировать: `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`
- `POSTGRES_PASSWORD` — надёжный пароль
- Обновить `DATABASE_URL` с новым паролем

### 7. Запустить

```bash
docker compose up -d --build
```

### 8. Проверить

```bash
docker compose ps          # все контейнеры running
curl http://localhost/api/health  # {"status":"ok"}
```

Открыть в браузере: `http://<IP>:3000`

---

## Настройка автодеплоя (GitHub Actions)

### Создать SSH ключ для деплоя

```bash
# На VPS
ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N ""
cat ~/.ssh/deploy_key.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/deploy_key  # скопировать приватный ключ
```

### Добавить секреты в GitHub

В репозитории → Settings → Secrets and variables → Actions:

- `VPS_HOST` — IP адрес VPS
- `VPS_USER` — `root`
- `VPS_SSH_KEY` — приватный ключ (содержимое `deploy_key`)

### Как работает

1. `git push origin master` → GitHub Actions запускается
2. Подключается к VPS по SSH
3. `git pull` → `docker compose up -d --build` → `docker image prune -f`
4. Даунтайм: ~10-30 секунд

---

## Обновление проекта

### Автоматически (рекомендуется)

```bash
git push origin master
# GitHub Actions сделает деплой автоматически
```

### Вручную (с локальной машины)

```bash
VPS_HOST=<IP> make deploy
```

### Вручную (на сервере)

```bash
ssh root@<IP>
cd /opt/life-analytics
make update
```

---

## Полезные команды

### С локальной машины (нужен VPS_HOST)

```bash
VPS_HOST=<IP> make deploy       # Деплой
VPS_HOST=<IP> make ssh          # Подключиться к VPS
VPS_HOST=<IP> make prod-logs    # Логи production
VPS_HOST=<IP> make prod-status  # Статус контейнеров
VPS_HOST=<IP> make prod-db      # Подключиться к БД
```

### На сервере

```bash
make up             # Запустить все сервисы
make down           # Остановить все сервисы
make logs           # Логи всех сервисов
make logs-backend   # Логи backend
make restart        # Перезапустить backend
make status         # Статус контейнеров
make update         # git pull + rebuild
```

### Бэкапы

```bash
make backup-up      # Запустить сервис бэкапов
make backup-logs    # Логи бэкапов
make backup-now     # Разовый бэкап
```

---

## Миграции базы данных

Миграции выполняются автоматически при старте backend.

### Как добавить миграцию

1. Добавь запись в `backend/app/migrations.py`:

```python
MIGRATIONS = [
    (1, "add_timezone_to_users", "ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'UTC'"),
]
```

2. Также обнови DDL в `database.py` `init_db()` (для чистых установок)
3. Запуши в master → автодеплой → миграция выполнится при старте

### Просмотр выполненных миграций

```bash
VPS_HOST=<IP> make prod-db
# В psql:
SELECT * FROM schema_migrations ORDER BY version;
```

---

## Troubleshooting

**Контейнер не запускается:**
```bash
docker compose logs backend     # логи backend
docker compose logs db          # логи PostgreSQL
```

**502 Bad Gateway / сайт недоступен:**
```bash
docker compose ps               # проверить статус
docker compose restart backend   # перезапустить
```

**Диск заполнен:**
```bash
docker system prune -af          # удалить все неиспользуемые образы и контейнеры
docker volume ls                 # проверить volumes
```

**Нехватка памяти (OOM):**
```bash
free -h                          # проверить RAM
docker stats                     # потребление памяти контейнерами
```
