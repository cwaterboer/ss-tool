FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    libpq-dev \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy and make entrypoint executable
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Expose port for Cloud Run
EXPOSE 8080

# Run entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
