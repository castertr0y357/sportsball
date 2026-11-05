# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Prevent Python from writing .pyc and buffer stdin/stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app/

# Collect static assets into staticfiles
RUN python manage.py collectstatic --noinput

# Create directory for SQLite and uploaded media files
RUN mkdir -p /app/data /app/media

# Default environment for container (override in production/docker-compose)
ENV DJANGO_SETTINGS_MODULE=church_leagues.settings

EXPOSE 8000

# Entrypoint script starts gunicorn
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py bootstrap_admin && python manage.py seed_demo_data && gunicorn church_leagues.wsgi:application --bind 0.0.0.0:$PORT --workers 3"]
