package com.example.tsldemo.DTOs.ResponseToFrontEnd;

import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Arrays;
import java.util.List;

import com.example.tsldemo.ScheduledPost;
import com.example.tsldemo.ENUMS.PlatformEnum;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * A scheduled post as the calendar wants it.
 *
 * <p>Carries both representations of the publish moment on purpose: {@code date}/{@code time}
 * are the wall-clock strings the grid renders and the modal edits, already resolved into the
 * post's own timezone, while {@code scheduledAt} is the unambiguous instant. Letting the
 * browser derive the former from the latter would reintroduce the timezone drift this feature
 * had — a viewer in another zone would see a different day.
 */
public record ScheduledPostRespDTO(

    @JsonProperty("id")
    String id,

    /** "linkedin" or "facebook" — the names the frontend's Platform union uses. */
    @JsonProperty("platform")
    String platform,

    @JsonProperty("date")
    String date,

    @JsonProperty("time")
    String time,

    @JsonProperty("scheduled_at")
    String scheduledAt,

    @JsonProperty("timezone")
    String timezone,

    @JsonProperty("message")
    String message,

    @JsonProperty("hashtags")
    List<String> hashtags,

    @JsonProperty("page_ids")
    List<Long> pageIds,

    @JsonProperty("status")
    String status,

    /** True when the platform holds the schedule rather than us. Shown as a hint in the UI. */
    @JsonProperty("native_scheduled")
    boolean nativeScheduled,

    @JsonProperty("platform_post_ids")
    List<String> platformPostIds,

    @JsonProperty("last_error")
    String lastError,

    @JsonProperty("created_at")
    String createdAt,

    @JsonProperty("updated_at")
    String updatedAt
) {

    private static final DateTimeFormatter DATE = DateTimeFormatter.ofPattern("yyyy-MM-dd");
    private static final DateTimeFormatter TIME = DateTimeFormatter.ofPattern("HH:mm");

    public static ScheduledPostRespDTO from(ScheduledPost post, ZoneId fallbackZone) {
        ZoneId zone = resolveZone(post.getTimezone(), fallbackZone);
        ZonedDateTime local = post.getScheduledAt().atZone(zone);

        return new ScheduledPostRespDTO(
                String.valueOf(post.getId()),
                platformName(post.getPlatform()),
                local.format(DATE),
                local.format(TIME),
                post.getScheduledAt().toString(),
                zone.getId(),
                post.getMessage(),
                post.getHashtags() == null ? List.of() : Arrays.asList(post.getHashtags()),
                post.getPageIds() == null ? List.of() : Arrays.asList(post.getPageIds()),
                post.getStatus().name().toLowerCase(),
                post.isNativeScheduled(),
                post.getPlatformPostIds() == null ? List.of() : Arrays.asList(post.getPlatformPostIds()),
                post.getLastError(),
                post.getCreatedAt() == null ? null : post.getCreatedAt().toString(),
                post.getUpdatedAt() == null ? null : post.getUpdatedAt().toString()
        );
    }

    /** A stored zone that the JVM no longer recognises (a renamed IANA id, or a row written by
     * an older build) must not take out the whole calendar listing — fall back rather than
     * throw, since the instant is correct either way and only the display zone is at stake. */
    private static ZoneId resolveZone(String timezone, ZoneId fallbackZone) {
        if (timezone == null || timezone.isBlank()) {
            return fallbackZone;
        }
        try {
            return ZoneId.of(timezone);
        } catch (Exception e) {
            return fallbackZone;
        }
    }

    /** META is the stored name for the Facebook connection; the UI calls it what the user does. */
    private static String platformName(PlatformEnum platform) {
        return platform == PlatformEnum.META ? "facebook" : platform.name().toLowerCase();
    }
}
