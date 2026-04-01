release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 2 --timeout 180 --threads 4
