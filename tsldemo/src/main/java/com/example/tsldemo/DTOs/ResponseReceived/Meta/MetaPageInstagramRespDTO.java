package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

/** Response of {@code GET /{page-id}?fields=instagram_business_account{id,username}}.
 *
 * Asking the Page node directly is Meta's own documented way to reach the linked Instagram
 * account. The /me/accounts edge nominally supports the same field by expansion, but omits it
 * often enough — silently, as a missing key rather than an error — that the edge result cannot
 * be treated as authoritative for "this Page has no Instagram account". */
public record MetaPageInstagramRespDTO(

    @JsonProperty("instagram_business_account")
    MetaInstagramAccount instagramBusinessAccount,

    /** The account linked through the Page's own settings rather than through Business Suite.
     *
     * Meta populates exactly one of these two fields depending on how the account was attached,
     * and the two linking routes are indistinguishable to a user who just followed the prompts in
     * the app: linking from Instagram's side fills this one, linking from Business Suite fills
     * instagram_business_account. Checking only the latter reports a genuinely linked account as
     * unlinked, so both are read and whichever is present wins. */
    @JsonProperty("connected_instagram_account")
    MetaInstagramAccount connectedInstagramAccount,

    @JsonProperty("id")
    String pageId

) {}
