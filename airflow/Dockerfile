# Use the official Airflow image as a base
FROM apache/airflow:2.10.0

# Set the working directory inside the container
WORKDIR /opt/airflow

# 1. Copy your requirements file first (to leverage Docker layer caching)
COPY requirements.txt .

# Install any custom python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copy your local DAGs folder into the image
# This assumes your local folder is named 'dags' and is in the same directory as this Dockerfile
COPY --chown=airflow:root ./dags /opt/airflow/dags