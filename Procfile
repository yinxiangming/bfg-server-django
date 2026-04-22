release: python manage.py migrate --noinput && python manage.py collectstatic --noinput && python manage.py bfg_prod_check
web: gunicorn config.wsgi --bind 0.0.0.0:5000 --workers 2 --timeout 180 --threads 4
