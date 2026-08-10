FROM ubuntu:22.04

# Prevent Ubuntu from pausing for timezone prompts
ENV DEBIAN_FRONTEND=noninteractive

# System deps needed to COMPILE dlib via pip below.
# NOTE: there is no "python3-dlib" apt package on Ubuntu - that line was the
# cause of the earlier "exit code: 100" build failure (apt couldn't find it).
RUN apt-get update -y && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libboost-python-dev \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# dlib compiles from C++ source and uses ALL cores in parallel by default -
# that spikes memory past 8GB on Render's build machines and gets OOM-killed.
# Forcing a single build job trades build speed for actually finishing.
ENV CMAKE_BUILD_PARALLEL_LEVEL=1

RUN pip3 install --no-cache-dir -r requirements.txt

# face_recognition_models on PyPI (0.3.0) is stale and often fails to
# register properly at runtime - install straight from source as the
# face_recognition library itself recommends.
RUN pip3 install --no-cache-dir git+https://github.com/ageitgey/face_recognition_models

RUN pip3 install --no-cache-dir gunicorn

COPY . .

EXPOSE 5000

# Start production server safely using python3 module
CMD ["python3", "-m", "gunicorn", "-w", "1", "--timeout", "120", "-b", "0.0.0.0:5000", "app:app"]
