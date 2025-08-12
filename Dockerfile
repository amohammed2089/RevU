FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Install system deps (if needed for Pillow, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy app files
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Expose Streamlit port
EXPOSE 8501

# Streamlit config for container runs
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Run the app
CMD ["streamlit", "run", "app.py"]
