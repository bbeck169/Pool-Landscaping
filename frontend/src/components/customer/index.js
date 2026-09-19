/**
 * Feb-2026 · Clickable Customer Data — barrel export.
 *
 * Import primitives via ``@/components/customer`` so sweep sites
 * don't multi-import individual files. Default exports are kept on
 * each source module too, for callers that prefer named default
 * imports.
 */
export { PhoneLink, default as PhoneLinkDefault } from "./PhoneLink";
export { AddressLink, default as AddressLinkDefault } from "./AddressLink";
export { CustomerLink, default as CustomerLinkDefault } from "./CustomerLink";
