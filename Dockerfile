FROM python:3.10-slim

# Install C++ dependencies required for dlib and OpenCV
RUN apt-get update && apt-get install -y \
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

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn

COPY . .

EXPOSE 5000

# Start production WSGI server
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]