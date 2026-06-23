#!/bin/sh

set -x

python --version

ls -la

python manage.py migrate

gunicorn config.wsgi:application --bind 0.0.0.0:$PORT