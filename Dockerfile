FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini .
COPY migrations migrations
COPY app app

USER 10001
EXPOSE 8000
CMD ["uvicorn", "--factory", "app.web.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
