/**
 * G1.5 · Feb-2026 — Localised copy for the customer-portal
 * agreement-renewal page.
 *
 * Kept intentionally small and self-contained — the customer portal
 * is a stand-alone surface (no auth, no full ``i18next`` bundle) and
 * we only need three strings per locale. Growing this catalog past
 * ~10 keys should trigger a refactor onto the main ``@/i18n`` pipe.
 *
 * Locale resolution order (first match wins):
 *   1. Explicit ``?locale=`` query parameter.
 *   2. ``summary.customer_locale`` returned by the backend
 *      (populated from the customer profile once available; today it
 *      may be absent, hence the graceful fallback).
 *   3. Browser ``navigator.language`` (first two chars).
 *   4. English (``en``) fallback.
 */
export const SUPPORTED_LOCALES = ["en", "es", "fr"];


export function pickLocale({ queryLocale, customerLocale }) {
  const candidates = [
    (queryLocale || "").toLowerCase().slice(0, 2),
    (customerLocale || "").toLowerCase().slice(0, 2),
    (typeof navigator !== "undefined" ? (navigator.language || "") : "")
      .toLowerCase().slice(0, 2),
    "en",
  ];
  for (const c of candidates) {
    if (SUPPORTED_LOCALES.includes(c)) return c;
  }
  return "en";
}


export const MESSAGES = {
  en: {
    "portal.renew.summary.loading":       "Loading your agreement…",
    "portal.renew.summary.headline":      "Renew your service agreement",
    "portal.renew.current_expires":       "Current expires",
    "portal.renew.new_expires":           "New expires",
    "portal.renew.price_label":           "Renewal price",
    "portal.renew.cta":                   "Renew Now",
    "portal.renew.cta.renewing":          "Renewing…",
    "portal.renew.cta.already_renewed":   "Already renewed",
    "portal.renew.confirmation_hint":
      "Confirmation will be sent to the email on file.",
    "portal.renew.success.title":         "You're all set",
    "portal.renew.success.body":
      "Your <b>{plan_name}</b> service agreement has been renewed. " +
      "A confirmation email is on its way.",
    "portal.renew.success.next_label":    "Next expiration",
    "portal.renew.error.title":
      "We can't process this renewal",
    "portal.renew.error.token_expired":
      "This renewal link has expired. Please contact us for a fresh link.",
    "portal.renew.error.token_invalid":
      "This renewal link is invalid. Please contact us to renew.",
    "portal.renew.error.agreement_state_invalid":
      "This agreement is no longer available for renewal. " +
      "It may have already been renewed.",
    "portal.renew.error.generic":
      "Something went wrong. Please try again in a moment.",
  },
  es: {
    "portal.renew.summary.loading":       "Cargando su contrato…",
    "portal.renew.summary.headline":      "Renueve su contrato de servicio",
    "portal.renew.current_expires":       "Vencimiento actual",
    "portal.renew.new_expires":           "Nuevo vencimiento",
    "portal.renew.price_label":           "Precio de renovación",
    "portal.renew.cta":                   "Renovar ahora",
    "portal.renew.cta.renewing":          "Renovando…",
    "portal.renew.cta.already_renewed":   "Ya renovado",
    "portal.renew.confirmation_hint":
      "La confirmación se enviará al correo registrado.",
    "portal.renew.success.title":         "Todo listo",
    "portal.renew.success.body":
      "Su contrato <b>{plan_name}</b> se ha renovado. " +
      "En breve recibirá un correo de confirmación.",
    "portal.renew.success.next_label":    "Próxima expiración",
    "portal.renew.error.title":
      "No podemos procesar esta renovación",
    "portal.renew.error.token_expired":
      "Este enlace de renovación ha caducado. " +
      "Contáctenos para obtener uno nuevo.",
    "portal.renew.error.token_invalid":
      "Este enlace de renovación no es válido. Contáctenos para renovar.",
    "portal.renew.error.agreement_state_invalid":
      "Este contrato ya no está disponible para renovación. " +
      "Es posible que ya se haya renovado.",
    "portal.renew.error.generic":
      "Algo salió mal. Por favor, inténtelo de nuevo en un momento.",
  },
  fr: {
    "portal.renew.summary.loading":       "Chargement de votre contrat…",
    "portal.renew.summary.headline":      "Renouvelez votre contrat de service",
    "portal.renew.current_expires":       "Expiration actuelle",
    "portal.renew.new_expires":           "Nouvelle expiration",
    "portal.renew.price_label":           "Prix de renouvellement",
    "portal.renew.cta":                   "Renouveler maintenant",
    "portal.renew.cta.renewing":          "Renouvellement…",
    "portal.renew.cta.already_renewed":   "Déjà renouvelé",
    "portal.renew.confirmation_hint":
      "La confirmation sera envoyée à l'adresse e-mail enregistrée.",
    "portal.renew.success.title":         "Tout est en règle",
    "portal.renew.success.body":
      "Votre contrat <b>{plan_name}</b> a été renouvelé. " +
      "Un e-mail de confirmation est en route.",
    "portal.renew.success.next_label":    "Prochaine expiration",
    "portal.renew.error.title":
      "Nous ne pouvons pas traiter ce renouvellement",
    "portal.renew.error.token_expired":
      "Ce lien de renouvellement a expiré. " +
      "Contactez-nous pour obtenir un nouveau lien.",
    "portal.renew.error.token_invalid":
      "Ce lien de renouvellement est invalide. " +
      "Contactez-nous pour renouveler.",
    "portal.renew.error.agreement_state_invalid":
      "Ce contrat n'est plus disponible pour renouvellement. " +
      "Il a peut-être déjà été renouvelé.",
    "portal.renew.error.generic":
      "Une erreur s'est produite. Veuillez réessayer dans un instant.",
  },
};


export function t(locale, key, vars = {}) {
  const dict = MESSAGES[locale] || MESSAGES.en;
  let raw = dict[key] || MESSAGES.en[key] || key;
  for (const [k, v] of Object.entries(vars || {})) {
    raw = raw.replace(new RegExp(`\\{${k}\\}`, "g"), v);
  }
  return raw;
}
