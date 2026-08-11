# Green Bridge - агрегатор для B2B сегмента в сельскохозяйственной области

## Описание 

Green Bridge - B2B-платформа на Django для взаимодействия поставщиков и покупателей сельскохозяйственной продукции. Проект объединяет каталог предложений, профили компаний, переговоры в чате, фиксацию договоренностей, отзывы и базовую аналитику по работе на платформе.

## Функционал проекта

- регистрация компаний с выбором роли: поставщик или покупатель
- подтверждение email при регистрации
- публикация и редактирование товарных предложений
- каталог товаров с фильтрацией по названию, категории, региону, компании и цене
- карточки компаний с отзывами и рейтингом
- чаты между покупателями и поставщиками по конкретному товару
- создание, подтверждение и отклонение договоренностей по сделке
- отзывы после подтвержденной сделки
- отдельная аналитика для поставщика и покупателя

## Стек

- Python 3.10
- Django 5.2
- PostgreSQL
- Pillow
- SMTP-почта для отправки кода подтверждения

## Структура проекта

```text
config/     настройки Django и корневые маршруты
core/       главная страница
products/   каталог, карточки товаров, CRUD предложений
users/      регистрация, авторизация, профили компаний, отзывы, аналитика
chats/      диалоги, сообщения и договоренности по сделкам
templates/  HTML-шаблоны
static/     стили и статические ресурсы
media/      загружаемые изображения
```

## Настройка проекта (полезные команды)

### Установка библиотек

```powershell
pip install -r requirements.txt
```

### Подготовка PostgreSQL

После создания БД проверьте настройки подключения в `config/settings.py`:

- `DATABASES['default']['NAME']`
- `DATABASES['default']['USER']`
- `DATABASES['default']['PASSWORD']`
- `DATABASES['default']['HOST']`
- `DATABASES['default']['PORT']`

По умолчанию проект настроен на PostgreSQL с базой `green_bridge_db`.

### 3. Настройка почты

Регистрация использует отправку кода подтверждения на email. По умолчанию включён
консольный backend: письмо не отправляется, а код подтверждения выводится в
терминал, где запущен Django.

Чтобы включить реальную отправку через SMTP, задайте переменные окружения перед
запуском проекта. Пример для PowerShell и почты Mail.ru:

```powershell
$env:EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend"
$env:EMAIL_HOST="smtp.mail.ru"
$env:EMAIL_PORT="587"
$env:EMAIL_USE_TLS="true"
$env:EMAIL_USE_SSL="false"
$env:EMAIL_HOST_USER="address@mail.ru"
$env:EMAIL_HOST_PASSWORD="password"
$env:DEFAULT_FROM_EMAIL="address@mail.ru"
python manage.py runserver
```

Используйте пароль приложения, созданный в настройках почтового сервиса, а не
пароль от почтового аккаунта. Для другого провайдера замените адрес SMTP-сервера,
порт и параметры TLS/SSL согласно его документации. Не добавляйте реальные
логины и пароли в `config/settings.py` или в Git.

Тогда код подтверждения будет выводиться в терминал вместо отправки письма.

### 4. Создание миграций и таблиц

```powershell
python manage.py makemigrations
python manage.py migrate
```

### 5. Создание администратора

```powershell
python manage.py createsuperuser
```

### 6. Запуск проекта

```powershell
python manage.py runserver
```

## Файловая система

- `/` - главная страница
- `/products/` - каталог товаров
- `/users/register/` - регистрация
- `/users/login/` - вход
- `/users/dashboard/` - личный кабинет компании
- `/users/analytics/` - аналитика
- `/chat/` - список диалогов
- `/admin/` - административная панель

## Проверки качества

```powershell
ruff format --check .
ruff check .
mypy chats core products users config
python manage.py check
python manage.py test
```

