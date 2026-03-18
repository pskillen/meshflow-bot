FROM python:3.14

ARG VERSION=development
ENV APP_VERSION=${VERSION}

WORKDIR /app

# Copy only the requirements file first to leverage Docker layer caching
COPY requirements.txt .

# Install dependencies (cache mount speeds up repeat builds)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy the rest of the application files
COPY . .

CMD ["python", "-m", "src.main"]
