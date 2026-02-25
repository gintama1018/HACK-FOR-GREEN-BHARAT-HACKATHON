FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV HOST=0.0.0.0
ENV PORT=8000

# Set the working directory
WORKDIR /app

# Install system dependencies (required for some Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file and install dependencies (BUILD time, not runtime)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY . .

# Make scripts executable
RUN chmod +x docker-entrypoint.sh start.sh

# Expose the correct port
EXPOSE 8000

# Use the lean Docker entrypoint (skips venv/pip install)
CMD ["bash", "docker-entrypoint.sh"]

