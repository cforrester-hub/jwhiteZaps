FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY ./services/dashboard-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared module
COPY ./shared ./shared

# Copy application code
COPY ./services/dashboard-service/src/ ./src/

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
