import React from "react";
import { Globe, Facebook, Star as StarIcon, Shield, Link as LinkIcon } from "lucide-react";

const ICONS = {
  google:   { Icon: Globe,     color: "#4285F4" },
  facebook: { Icon: Facebook,  color: "#1877F2" },
  yelp:     { Icon: StarIcon,  color: "#D32323" },
  bbb:      { Icon: Shield,    color: "#005B9A" },
  custom:   { Icon: LinkIcon,  color: "#6B7280" },
};

/** Coloured platform pill icon reused across platforms/dashboard/widget. */
export function PlatformIcon({ code, size = 16, className = "" }) {
  const entry = ICONS[(code || "").toLowerCase()] || ICONS.custom;
  const { Icon, color } = entry;
  return (
    <span className={`inline-flex items-center justify-center ${className}`}
           style={{ color }}>
      <Icon size={size} />
    </span>
  );
}

export default PlatformIcon;
