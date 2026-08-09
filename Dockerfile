FROM python:3.10-slim-bullseye

# Prevent Linux from pausing to ask Y/N questions during installation
ENV DEBIAN_FRONTEND=noninteractive

# Use a more robust install command
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn

COPY . .

EXPOSE 5000

# Start production server
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]