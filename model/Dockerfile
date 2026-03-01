FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY common/ common/
COPY configs/ configs/
COPY data_preprocessing.py .

CMD ["python", "-u", "data_preprocessing.py"]
