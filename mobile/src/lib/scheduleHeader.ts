/** TD-mobile-header-layout-cleanup · below this width (dp) the Schedule header moves
 *  Sync-route + Refresh into the status strip so the title row keeps bell + menu only. */
export const SCHEDULE_COMPACT_HEADER_MAX_DP = 360;

export function isCompactScheduleHeader(width: number): boolean {
  return width < SCHEDULE_COMPACT_HEADER_MAX_DP;
}
