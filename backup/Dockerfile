FROM python:3.12-alpine
ENV PYTHONUNBUFFERED=1
RUN apk add --no-cache postgresql16-client gzip
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backup.py .
CMD ["python", "backup.py"]
