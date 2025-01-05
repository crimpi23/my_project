FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "run.py"]

ENV FLASK_APP=run.py
ENV FLASK_ENV=development

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD curl --fail http://localhost:5000/ || exit 1
