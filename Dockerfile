FROM python:3.11

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the code for image build (dev will override via bind mount)
COPY . .

EXPOSE 8000
CMD ["python", "cetaf_survey_api/manage.py", "runserver", "0.0.0.0:8000"]
