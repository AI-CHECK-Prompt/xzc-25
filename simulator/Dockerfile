FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir httpx==0.27.0

COPY . /app

CMD ["python", "inject_data.py", "--project", "阳光城A区一标段"]
