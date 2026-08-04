package com.example.tsldemo.CrossPlatformAPI;

import com.azure.storage.blob.BlobClient;
import com.azure.storage.blob.BlobContainerClient;
import com.azure.storage.blob.BlobServiceClient;
import com.azure.storage.blob.BlobServiceClientBuilder;
import com.azure.storage.blob.sas.BlobSasPermission;
import com.azure.storage.blob.sas.BlobServiceSasSignatureValues;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.time.OffsetDateTime;
import java.util.UUID;

@Service
public class VideoStorageService {

    @Value("${azure.storage.connection-string}")
    private String connectionString;

    @Value("${azure.storage.container-name}")
    private String containerName;

    public String uploadAndGetSasUrl(byte[] bytes, String originalFilename, long size) {
        BlobServiceClient blobServiceClient = new BlobServiceClientBuilder()
                .connectionString(connectionString)
                .buildClient();

        BlobContainerClient containerClient = blobServiceClient.getBlobContainerClient(containerName);

        String safeName = (originalFilename == null || originalFilename.isBlank())
                ? "video"
                : originalFilename;

        String blobName = "instagram-uploads/" + UUID.randomUUID() + "-" + safeName;
        BlobClient blobClient = containerClient.getBlobClient(blobName);

        blobClient.upload(new ByteArrayInputStream(bytes), size, true);

        BlobSasPermission permission = new BlobSasPermission().setReadPermission(true);
        OffsetDateTime expiry = OffsetDateTime.now().plusMinutes(15);

        BlobServiceSasSignatureValues sasValues =
                new BlobServiceSasSignatureValues(expiry, permission);

        String sasToken = blobClient.generateSas(sasValues);
        return blobClient.getBlobUrl() + "?" + sasToken;
    }
}