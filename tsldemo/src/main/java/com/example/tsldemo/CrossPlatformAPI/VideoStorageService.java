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
        // Must outlast the whole publish, not just the upload: Instagram fetches this URL itself
        // and keeps re-reading it while it transcodes, so an expiry shorter than the publish
        // timeout in InstagramAPIService would pull the file out from under a slow transcode.
        // That timeout is per-account and a single upload can be published to several accounts in
        // sequence, so this has to cover the sum, not one of them. Read-only access to one
        // unguessable blob name, so the longer window costs little.
        OffsetDateTime expiry = OffsetDateTime.now().plusMinutes(60);

        BlobServiceSasSignatureValues sasValues =
                new BlobServiceSasSignatureValues(expiry, permission);

        String sasToken = blobClient.generateSas(sasValues);
        return blobClient.getBlobUrl() + "?" + sasToken;
    }
}