# Use the official Azure Functions Python base image
FROM mcr.microsoft.com/azure-functions/python:4-python3.11-appservice

ENV AzureWebJobsScriptRoot=/home/site/wwwroot
ENV AzureFunctionsJobHost__Logging__Console__IsEnabled=true

RUN apt-get update && apt-get install poppler-utils -y

COPY webhook/requirements.txt /home/site/wwwroot/requirements.txt
RUN cd /home/site/wwwroot && pip install --no-cache-dir -r requirements.txt
# Copy the function app code to the container
COPY webhook /home/site/wwwroot