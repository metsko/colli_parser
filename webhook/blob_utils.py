import os
import asyncio
import polars as pl
from azure.storage.blob.aio import BlobServiceClient as AsyncBlobServiceClient, ContainerClient as AsyncContainerClient
from loguru import logger

async def get_async_container_client(name: str) -> AsyncContainerClient:
    """Get an async container client for Azure Blob Storage with timeout."""
    connect_str = os.getenv("AzureWebJobsStorage")
    if not connect_str:
        logger.error("AzureWebJobsStorage is not set.")
        raise ValueError("AzureWebJobsStorage environment variable is not set")
    
    try:

        blob_service_client = AsyncBlobServiceClient.from_connection_string(conn_str=connect_str)
        container_client = blob_service_client.get_container_client(name)
        
        try:
            if not await container_client.exists():
                await container_client.create_container()
        except asyncio.TimeoutError:
            logger.warning(f"Timeout creating container {name}, assuming it exists")
        except Exception as e:
            logger.warning(f"Container creation error (may already exist): {str(e)}")
        
        return container_client
    except Exception as e:
        logger.error(f"Error getting container client: {str(e)}")
        raise

async def async_azure_upload_ndjson(df: pl.DataFrame, file_name: str, timeout: float = 10.0):
    """Upload a Polars DataFrame to Azure Blob Storage as NDJSON format, using async operations with timeout."""
    try:
        # Get container client with timeout
        container_client = await get_async_container_client("function")
        
        # Convert to NDJSON format
        ndjson_content = df.to_pandas().to_json(orient="records", lines=True)
        
        # Get blob client and upload with timeout
        blob_client = container_client.get_blob_client(file_name)
        
        # Use asyncio.wait_for to prevent hanging
        try:
            await asyncio.wait_for(
                blob_client.upload_blob(ndjson_content, overwrite=True),
                timeout=timeout
            )
            logger.info(f"Uploaded NDJSON to Azure container 'function' as {file_name}.")
        except asyncio.TimeoutError:
            logger.error(f"Timeout uploading NDJSON to {file_name}")
            raise TimeoutError(f"Blob upload operation timed out after {timeout} seconds")
            
    except Exception as e:
        logger.error(f"Error uploading NDJSON: {str(e)}")
        raise
