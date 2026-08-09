FROM ubuntu:22.04

# Prevent Ubuntu from pausing for timezone prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install Python and the heavily pre-compiled AI libraries natively!
# This completely bypasses the 8GB memory crash.
RUN apt-get update -y && apt-get install -y \
    python3 \
    python3-pip \
    python3-dlib \
    python3-opencv \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Install the remaining Python packages
RUN pip3 install --no-cache-dir -r requirements.txt
RUN pip3 install --no-cache-dir gunicorn

COPY . .

EXPOSE 5000

# Start production server safely using python3 module
CMD ["python3", "-m", "gunicorn", "-w", "1", "--timeout", "120", "-b", "0.0.0.0:5000", "app:app"]