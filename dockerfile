FROM python:3.13-slim

# Evita archivos .pyc y permite ver logs inmediatamente
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Actualizar pip
RUN pip install --no-cache-dir --upgrade pip

# Copiar requirements
COPY extractor_bank/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copiar la aplicación
COPY extractor_bank/ .

# Puerto de Django/Gunicorn
EXPOSE 8000

# Aplicar migraciones y arrancar Gunicorn
CMD ["sh", "-c", "python manage.py migrate && gunicorn extractor_bank.wsgi:application --bind 0.0.0.0:8000"]