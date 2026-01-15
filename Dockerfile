# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Install AWS Lambda Adapter (Enables Flask to run on Lambda)
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 /lambda-adapter /opt/extensions/lambda-adapter

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
# gcc and others might be needed for some python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Download the spacy model
RUN python -m spacy download en_core_web_lg

# Copy the rest of the application code
COPY . .

# Expose port 5000 for Flask
EXPOSE 5000
ENV PORT=5000

# Define environment variable
ENV FLASK_APP=app.py

# Run app.py when the container launches
CMD ["python", "app.py"]
