# Use the official Miniconda environment (built for AI)
FROM continuumio/miniconda3

# Install basic visual tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Download pre-compiled dlib instantly!
RUN conda install -y -c conda-forge dlib

COPY requirements.txt .

# Install the rest
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn

COPY . .

EXPOSE 5000

# Start production server
CMD ["gunicorn", "-w", "1", "--timeout", "120", "-b", "0.0.0.0:5000", "app:app"]