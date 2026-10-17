# Trusted sources — App Store submission

## PRIMARY (Apple)
- https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications — screenshot sizes, required slots, alpha rule
- https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications — preview length, codecs, resolutions
- https://developer.apple.com/help/app-store-connect/reference/app-information/app-information — name, subtitle, privacy URL, category
- https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information — promo text, description, keywords (bytes), What's New, review notes
- https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-information — IAP name/description limits, promo image
- https://developer.apple.com/app-store/review/guidelines/ — App Review Guidelines (2.1, 2.3.x, 3.1.1, 5.1.x, 5.2)
- https://developer.apple.com/app-store/app-privacy-details/ — privacy nutrition labels
- https://developer.apple.com/documentation/bundleresources/privacy-manifest-files — privacy manifests
- https://developer.apple.com/app-store/marketing/guidelines/ — badge, product images, trademark wording
- https://developer.apple.com/app-store/product-page/ — product page guidance
- https://developer.apple.com/design/resources/ — Figma kits and product bezels
- https://developer.apple.com/news/ — announcements of new requirements (SDK minimums, new sizes)
- https://developer.apple.com/help/app-review/ — App Review Help: complete review, screenshots 2.3.3, purpose strings, account deletion, IAP in sandbox, compatible devices, appeals, expedite, removals, App Store Improvements (author edit 2026-10-17)
- https://developer.apple.com/app-store/asset-best-practices/ — asset best practices referenced by 2.3.14

## PRIMARY (Apple) — App Store Connect forms, field by field (references/app-store-connect-fields.md, read 2026-10-14)
Prefix https://developer.apple.com/help/app-store-connect/
- create-an-app-record/add-a-new-app — New App dialog: platforms, name, language, bundle ID, SKU, user access
- manage-app-information/set-an-app-age-rating — age rating flow, override, Made for Kids
- reference/app-information/age-ratings-values-and-definitions — every age-rating item and the rating it triggers
- manage-app-information/provide-a-custom-license-agreement — license agreement
- manage-app-information/complete-the-digital-goods-and-services-questionnaire — digital goods question
- manage-compliance-information/manage-european-union-digital-services-act-trader-requirements — DSA trader status
- manage-app-pricing/set-a-price — app price schedule
- manage-your-apps-availability/manage-availability-for-your-app-on-the-app-store — countries, pre-orders
- manage-your-apps-availability/manage-availability-of-iphone-and-ipad-apps-on-macs-with-apple-silicon — Mac checkbox
- manage-your-apps-availability/manage-availability-of-iphone-and-ipad-apps-on-apple-vision-pro — Vision Pro checkbox
- manage-app-information/set-a-tax-category — app tax category
- manage-app-information/manage-app-privacy — App Privacy flow, privacy URLs
- reference/app-information/app-privacy — privacy properties
- manage-app-accessibility/overview-of-accessibility-nutrition-labels — accessibility features
- manage-app-accessibility/manage-accessibility-nutrition-labels — accessibility flow, draft until live
- reference/app-information/required-localizable-and-editable-properties — required/editable matrix
- manage-app-information/manage-your-app-store-assets — screenshots, Asset Library, Media Manager
- manage-builds/choose-a-build-to-submit — build selection, Missing Compliance
- manage-app-information/overview-of-export-compliance — export compliance
- manage-app-information/determine-and-upload-app-encryption-documentation — encryption documentation
- reference/app-information/export-compliance-documentation-for-encryption — which documentation
- test-a-beta-version/provide-export-compliance-information-for-beta-builds — compliance on builds
- manage-your-apps-availability/select-an-app-store-version-release-option — release options, Release This Version
- update-your-app/release-a-version-update-in-phases — phased release (updates only)
- manage-submissions-to-app-review/submit-an-app — Add for Review, Submit for Review
- manage-submissions-to-app-review/submit-an-in-app-purchase — first IAP goes with a version
- manage-in-app-purchases/create-consumable-or-non-consumable-in-app-purchases — IAP type, reference name, product ID
- reference/in-app-purchases-and-subscriptions/in-app-purchase-types — IAP types
- manage-in-app-purchases/set-availability-for-in-app-purchases — IAP availability
- manage-in-app-purchases/set-a-price-for-an-in-app-purchase — IAP price
- manage-in-app-purchases/view-and-edit-in-app-purchase-information — IAP localization, image, review information
- configure-in-app-purchase-settings/set-a-tax-category-for-in-app-purchases — IAP tax category
- configure-in-app-purchase-settings/turn-on-family-sharing-for-in-app-purchases — Family Sharing (can't be undone)
- test-a-beta-version/provide-test-information — TestFlight test information
- https://developer.apple.com/documentation/bundleresources/information-property-list/itsappusesnonexemptencryption — the encryption key
- https://developer.apple.com/documentation/appstoreconnectapi/ — attribute pages for AgeRatingDeclaration, App, AppStoreVersion (usesIdfa deprecated), AppStoreReviewDetail, BetaAppLocalization, BetaAppReviewDetail, BetaBuildLocalization: field names and allowed answers

## PRIMARY (SDK vendors, for their own SDK only)
- https://developers.google.com/admob/ios/privacy/data-disclosure — Google Mobile Ads SDK data disclosure
- https://developers.google.com/admob/ios/privacy — UMP consent SDK

## SECONDARY
- Third-party ASO and screenshot-size guides (they often disagree; never trust a size they quote without Apple's page)
- Search topic: "App Store Connect screenshot requirements <current month year>"
