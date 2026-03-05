# Деплой Life Analytics на VPS

Пошаговая инструкция: от нового сервера до работающего приложения.

## Информация о проекте

- **Хостинг:** VDSina (https://cp.vdsina.ru)
- **ОС:** Ubuntu 22.04+ или Debian 12+
- **Репозиторий:** https://github.com/kudrmax/life-analytics.git
- **Расположение на сервере:** `/opt/life-analytics`
- **Порты:** 3000 (фронтенд), 8000 (бэкенд API)

---

## Часть 1. GitHub (один раз)

### 1.1. Создать репозиторий

Если репозиторий ещё не создан — зайдите на https://github.com/new:
- Имя: `life-analytics`
- Видимость: Private (или Public)
- Нажмите "Create repository"

### 1.2. Привязать локальный проект

На вашем Mac:

```bash
cd /путь/к/life-analytics

# Проверить, есть ли уже remote:
git remote -v

# Если remote нет — добавить:
git remote add origin https://github.com/<ваш-username>/life-analytics.git

# Если remote есть, но с неправильным URL — заменить:
git remote set-url origin https://github.com/<ваш-username>/life-analytics.git

# Запушить код:
git push -u origin master
```

Откройте `https://github.com/<ваш-username>/life-analytics` — убедитесь, что код появился.

---

## Часть 2. Подготовка Mac (один раз)

### 2.1. Скопировать SSH-ключ на сервер

Это нужно, чтобы подключаться к серверу без пароля (и чтобы `make deploy` работал):

```bash
ssh-copy-id root@<IP-адрес-сервера>
# Введите пароль сервера (из панели VDSina или из email)
```

Проверьте — должно пускать без пароля:

```bash
ssh root@<IP-адрес-сервера>
```

---

## Часть 3. Настройка VPS (один раз)

Подключитесь к серверу:

```bash
ssh root@<IP-адрес-сервера>
```

### 3.1. Обновить систему и установить Docker

```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
apt install -y make git
```

Запустить Docker и включить автозапуск:

```bash
systemctl start docker
systemctl enable docker
```

### 3.2. Настроить swap (подстраховка для 2 GB RAM)

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### 3.3. Настроить firewall

```bash
ufw allow 22    # SSH
ufw allow 3000  # фронтенд
ufw allow 8000  # бэкенд API
ufw enable
```

### 3.4. Склонировать проект с GitHub

Если репозиторий **публичный**:

```bash
git clone https://github.com/<ваш-username>/life-analytics.git /opt/life-analytics
```

Если репозиторий **приватный** — нужен Personal Access Token:
1. Зайдите: https://github.com/settings/tokens
2. "Generate new token (classic)" → галочка `repo` → Generate
3. Скопируйте токен

```bash
git clone https://github.com/<ваш-username>/life-analytics.git /opt/life-analytics
# Логин: ваш GitHub username
# Пароль: вставить токен (НЕ пароль от GitHub)
```

### 3.5. Создать файл .env

```bash
cd /opt/life-analytics
cp .env.example .env
nano .env
```

**Формат файла `.env`:**

```
POSTGRES_USER=la_user
POSTGRES_PASSWORD=MyStr0ngPass2026
POSTGRES_DB=life_analytics

DATABASE_URL=postgresql://la_user:MyStr0ngPass2026@db:5432/life_analytics
LA_SECRET_KEY=случайная_строка_для_шифрования
```

**Важные правила:**

1. **`DATABASE_URL` формат** — строго:
   ```
   postgresql://ПОЛЬЗОВАТЕЛЬ:ПАРОЛЬ@db:5432/БАЗА
   ```
   - `db` — это имя сервиса PostgreSQL в Docker Compose (не IP, не localhost)
   - `5432` — стандартный порт PostgreSQL
   - Пароль должен совпадать с `POSTGRES_PASSWORD`

2. **Пароли и ключи** — НЕ используйте символы `@`, `:`, `/`, `#`, `*` — они ломают формат URL и переменных окружения

3. **Сгенерировать надёжные значения:**
   ```bash
   # Для LA_SECRET_KEY:
   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'

   # Для POSTGRES_PASSWORD:
   python3 -c 'import secrets; print(secrets.token_urlsafe(16))'
   ```

Сохранить в nano: `Ctrl+O` → Enter → `Ctrl+X`

### 3.6. Запустить

```bash
cd /opt/life-analytics
make up
```

Подождите 1–2 минуты. Проверьте:

```bash
docker compose ps
# Все 3 сервиса (db, backend, frontend) должны быть "Up"

curl http://localhost:8000/api/health
# Должен вернуть: {"status":"ok"}
```

### 3.7. Проверить в браузере

- **http://IP:3000** — фронтенд (основной интерфейс)
- **http://IP:8000/docs** — Swagger документация API
- **http://IP:8000/api/health** — проверка здоровья

### 3.8. Сменить пароль root

```bash
passwd
```

---

## Часть 4. Ежедневная работа

### Обновить сервер после изменений в коде

**Шаг 1.** Запушить код на GitHub (с Mac):

```bash
git add -A && git commit -m "описание изменений" && git push
```

**Шаг 2.** Задеплоить (с Mac, одна команда):

```bash
VPS_HOST=<IP> make deploy
```

Эта команда подключается к серверу по SSH, делает `git pull` и пересобирает контейнеры.

### Другие полезные команды (с Mac)

```bash
VPS_HOST=<IP> make ssh          # Подключиться к серверу
VPS_HOST=<IP> make prod-logs    # Логи production
VPS_HOST=<IP> make prod-status  # Статус контейнеров
VPS_HOST=<IP> make prod-db      # Подключиться к production БД
```

### Команды на сервере

```bash
make up             # Запустить все сервисы
make down           # Остановить все сервисы
make logs           # Логи всех сервисов
make logs-backend   # Логи backend
make restart        # Перезапустить backend
make update         # git pull + rebuild
```

---

## Часть 5. Автодеплой через GitHub Actions (опционально)

Позволяет автоматически обновлять сервер при `git push` в master.

### 5.1. Создать SSH-ключ для деплоя (на VPS)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N ""
cat ~/.ssh/deploy_key.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/deploy_key  # скопировать приватный ключ
```

### 5.2. Добавить секреты в GitHub

В репозитории → Settings → Secrets and variables → Actions → New repository secret:

| Секрет | Значение |
|---|---|
| `VPS_HOST` | IP-адрес вашего сервера |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | Содержимое `~/.ssh/deploy_key` (приватный ключ целиком) |

### 5.3. Как работает

1. `git push origin master` → GitHub Actions запускается
2. Подключается к VPS по SSH
3. `git pull` → `docker compose up -d --build` → `docker image prune -f`
4. Даунтайм: ~10-30 секунд

---

## Часть 6. Бэкапы (опционально)

### Настройка

1. Получите OAuth-токен Яндекс Диска: https://yandex.ru/dev/disk/poligon/
2. Добавьте в `.env` на сервере:
   ```
   YADISK_TOKEN=ваш-токен
   ```
3. Запустите:
   ```bash
   make backup-up
   ```

### Управление

```bash
make backup-up       # Запустить сервис бэкапов
make backup-down     # Остановить
make backup-logs     # Посмотреть логи
make backup-now      # Разовый бэкап прямо сейчас
```

### Восстановление из бэкапа

```bash
# Скачать файл с Яндекс Диска, распаковать и загрузить:
gunzip life_analytics_2026-03-04_12-00-00.sql.gz
docker exec -i life-analytics-db-1 psql -U la_user -d life_analytics < life_analytics_2026-03-04_12-00-00.sql
```

---

## Troubleshooting

### Backend не запускается

```bash
make logs-backend
```

Частые причины:
- **`invalid literal for int()`** — неправильный формат `DATABASE_URL` в `.env`. Проверьте формат: `postgresql://user:password@db:5432/dbname`. Пароль не должен содержать `@`, `:`, `/`
- **`Connection refused`** — БД ещё не готова. Подождите 30 секунд и проверьте `docker compose ps`

### Забыли формат DATABASE_URL

```
postgresql://ПОЛЬЗОВАТЕЛЬ:ПАРОЛЬ@db:5432/БАЗА_ДАННЫХ
             └── POSTGRES_USER     │         └── POSTGRES_DB
                           └── POSTGRES_PASSWORD
                                       │
                                      db — имя сервиса в docker-compose.yml
                                    5432 — стандартный порт PostgreSQL
```

### Пересоздать БД с нуля

```bash
cd /opt/life-analytics
docker compose down -v   # -v удаляет данные БД!
make up
```

### Контейнер не запускается / 502 Bad Gateway

```bash
docker compose ps               # проверить статус
docker compose logs backend     # логи backend
docker compose logs db          # логи PostgreSQL
docker compose restart backend  # перезапустить
```

### Диск заполнен

```bash
docker system prune -af   # удалить неиспользуемые образы
docker volume ls           # проверить volumes
```

### Нехватка памяти

```bash
free -h           # проверить RAM
docker stats      # потребление контейнерами
```

### Docker не запущен

```bash
# Cannot connect to the Docker daemon
systemctl start docker
systemctl enable docker   # автозапуск после перезагрузки
```
