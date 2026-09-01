FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

# 1. Added libopenblas-dev for optimized facial recognition processing
RUN apt-get update && apt-get install -y cmake g++ make libopenblas-dev

# 2. THE MAGIC LINE: Forces the compiler to use only 1 CPU core so it doesn't crash the server's memory!
ENV CMAKE_BUILD_PARALLEL_LEVEL=1

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# Start production server
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "app:app"]