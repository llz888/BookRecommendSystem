"""Django settings for core project."""
import os
from pathlib import Path

X_FRAME_OPTIONS = 'SAMEORIGIN'

BASE_DIR = Path(__file__).resolve().parent.parent

# 环境变量控制：本地不设置也能跑（DEBUG=1），服务器上设 DJANGO_DEBUG=0
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'

# 生产环境必须通过 DJANGO_SECRET_KEY 注入一个全新的密钥，不要沿用下面这个开发密钥
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-el)&^e)-v0n=-*2px_2ktc=7q)0@%$@_j%2i#9(yjv)_ub^mdz',
)

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')
    if h.strip()
]

INSTALLED_APPS = [
    # 'simpleui',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'books',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# 本地开发默认连本地 MySQL，服务器通过环境变量覆盖
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME', 'books_db'),
        'USER': os.environ.get('DB_USER', 'book_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'BookDev_2026'),
        'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
        'PORT': os.environ.get('DB_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
        'CONN_MAX_AGE': 0,
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
# collectstatic 的输出目录，生产环境交给 nginx 服务
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 会话存数据库。多进程部署时内存会话会在不同 worker 之间丢失，表现为随机掉登录状态
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

# ===== 大模型配置 =====
# 本地 Ollama 默认值；换成云端 API 时只需改这三个环境变量
AI_BASE_URL = os.environ.get('AI_BASE_URL', 'http://127.0.0.1:11434/v1/')
AI_API_KEY = os.environ.get('AI_API_KEY', 'ollama')
AI_MODEL = os.environ.get('AI_MODEL', 'deepseek-r1:7b')
# AI 生成可能很慢，客户端超时放宽到 120 秒
AI_TIMEOUT = float(os.environ.get('AI_TIMEOUT', '120'))

# ===== 反向代理 / HTTPS =====
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if o.strip()
]

# 配了 HTTPS 再打开（DJANGO_HTTPS=1），纯 IP + HTTP 访问时务必保持关闭
if os.environ.get('DJANGO_HTTPS', '0') == '1':
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True

# ===== 日志 =====
# 控制台输出便于开发排查，文件输出便于上线后回溯，单文件 5MB 轮转 3 份
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'django.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 3,
            'encoding': 'utf-8',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django.request': {
            'handlers': ['console', 'file'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}