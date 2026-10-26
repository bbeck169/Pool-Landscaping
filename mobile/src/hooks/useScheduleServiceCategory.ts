/** M3a · Schedule Service Category state, persisted in AsyncStorage (same pattern as the crew filter). */
import { useCallback, useEffect, useState } from "react";

import { storage } from "@/src/utils/storage";
import { normalizeServiceCategory, SERVICE_CATEGORY_KEY, type ServiceCategoryBucket } from "@/src/lib/scheduleServiceCategory";

export function useScheduleServiceCategory() {
  const [category, setCategory] = useState<ServiceCategoryBucket>("All");

  useEffect(() => {
    storage.getItem<string>(SERVICE_CATEGORY_KEY, "All")
      .then((v: any) => setCategory(normalizeServiceCategory(v)))
      .catch(() => {});
  }, []);

  const select = useCallback((bucket: unknown) => {
    const next = normalizeServiceCategory(bucket);
    setCategory(next);
    (next === "All" ? storage.removeItem(SERVICE_CATEGORY_KEY) : storage.setItem(SERVICE_CATEGORY_KEY, next)).catch(() => {});
  }, []);

  return [category, select] as const;
}
