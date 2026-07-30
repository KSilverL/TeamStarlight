package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

/** The Instagram Business/Creator account linked to a Facebook Page, as returned by the
 * `instagram_business_account` field on the /me/accounts edge.
 *
 * Publishing to Instagram is addressed by THIS id, not by the Page id — the Page is only how
 * the account is reached and where the usable access token comes from. A Page with no linked
 * Instagram account simply omits the field, which is how {@code null} arises here: it means
 * "this Page cannot be published to", not an error.
 *
 * The id is a String rather than a Long deliberately. Graph returns numeric ids as JSON strings
 * and documents them as opaque; treating them as text avoids ever having to care whether one
 * still fits in 64 bits. */
public record MetaInstagramAccount(

    @JsonProperty("id")
    String igUserId,

    @JsonProperty("username")
    String username

) {}
