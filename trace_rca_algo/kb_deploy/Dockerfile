# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

ENV GIT_PYTHON_REFRESH=quiet
ENV MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING=false

# Command to run the application
CMD ["python", "main.py"]