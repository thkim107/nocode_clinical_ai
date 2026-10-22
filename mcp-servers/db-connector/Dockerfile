FROM docker.io/library/python:3.11-slim

# Set working directory
WORKDIR /app/mcp-servers

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p /app/data /app/dbdata

# Set environment variables
ENV PYTHONPATH=/app/mcp-servers
ENV DB_CONFIG_PATH=/app/mcp-servers/config/databases.yaml
ENV METADATA_BASE_PATH=/app/mcp-servers

# Expose port (if needed for HTTP mode)
EXPOSE 8000

# Run the server
CMD ["python", "main.py"]
