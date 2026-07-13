export const DISPO: Record<string, { label: string; color: string; icon: string }> = {
  not_home: { label: "Not Home", color: "#64748B", icon: "home-outline" },
  not_interested: { label: "Not Interested", color: "#DC2626", icon: "close-circle" },
  callback: { label: "Callback", color: "#A16207", icon: "time" },
  interested: { label: "Interested", color: "#0284C7", icon: "star" },
  sold: { label: "Sold", color: "#16A34A", icon: "checkmark-circle" },
};
export const ORDER = ["sold", "interested", "callback", "not_interested", "not_home"];

// Open-lead pipeline statuses (leads not won/lost). Used for color-coded badges + map pins.
export const LEAD_STATUS: Record<string, { label: string; color: string }> = {
  new: { label: "New", color: "#0284C7" },
  contacted: { label: "Contacted", color: "#D97706" },
  quoted: { label: "Quoted", color: "#7C3AED" },
};
export const leadStatusMeta = (s?: string) => LEAD_STATUS[(s || "new").toLowerCase()] || { label: s || "Lead", color: "#0284C7" };
