# Dockerfile para desplegar a Sofía en Dokploy
FROM python:3.11-slim

# Evitar que Python genere archivos .pyc y activar salida en tiempo real para logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema necesarias para LiveKit si las hubiera
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Comando por defecto para iniciar el agente
CMD ["python", "agent.py", "start"]
