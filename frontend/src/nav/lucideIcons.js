/**
 * Phase K75 · Step B · Feb-2026 — Quick-pin icon whitelist.
 *
 * The pin schema stores a stringly-keyed ``iconKey`` (not a React
 * component reference) so pins survive JSON serialization to the
 * backend and back. This module is the SINGLE SOURCE OF TRUTH for
 * the (key → lucide-react component) mapping — the backend
 * validates ``iconKey`` against the frozen key list below via a
 * shipped JSON copy so both sides stay in sync.
 *
 * Consumers:
 *   • ``layouts/AppLayout.jsx``  · QuickPinsRail — resolve pin →
 *     rendered <Icon/>.
 *   • ``components/nav/AddPinModal.jsx`` — show the icon in the
 *     picker row.
 *   • ``nav/defaultQuickPins.js`` — seed defaults reference these
 *     keys.
 *   • ``backend/routers/quick_pins.py`` · ``ICON_WHITELIST`` — the
 *     same key list, mirrored for PUT validation.
 *
 * When adding a new icon: add it here AND in
 * ``backend/routers/quick_pins.py::ICON_WHITELIST``. The K75
 * pytest contract test regexes both files so they can't drift.
 */
import {
  LayoutDashboard,
  Wrench,
  CalendarDays,
  Receipt,
  CreditCard,
  Users,
  UserPlus,
  FileText,
  Waves,
  Clock,
  Timer,
  BarChart3,
  Settings,
  DoorOpen,
  LayoutGrid,
  GraduationCap,
  UserCircle,
  Home,
  ShoppingCart,
  Truck,
  Star,
  Bell,
  MessageSquare,
  Mail,
  Map,
  ClipboardList,
  Package,
  Tag,
  Sparkles,
  Bot,
  BookOpen,
  ShieldCheck,
  Building2,
  Camera,
  ExternalLink,
} from "lucide-react";


export const ICON_MAP = {
  layout_dashboard: LayoutDashboard,
  wrench: Wrench,
  calendar_days: CalendarDays,
  receipt: Receipt,
  credit_card: CreditCard,
  users: Users,
  user_plus: UserPlus,
  file_text: FileText,
  waves: Waves,
  clock: Clock,
  timer: Timer,
  bar_chart_3: BarChart3,
  settings: Settings,
  door_open: DoorOpen,
  layout_grid: LayoutGrid,
  graduation_cap: GraduationCap,
  user_circle: UserCircle,
  home: Home,
  shopping_cart: ShoppingCart,
  truck: Truck,
  star: Star,
  bell: Bell,
  message_square: MessageSquare,
  mail: Mail,
  map: Map,
  clipboard_list: ClipboardList,
  package: Package,
  tag: Tag,
  sparkles: Sparkles,
  bot: Bot,
  book_open: BookOpen,
  shield_check: ShieldCheck,
  building_2: Building2,
  camera: Camera,
  external_link: ExternalLink,
};


/**
 * The lucide-react keys the backend accepts for
 * ``users.preferences.quickPins[i].iconKey``. Frozen tuple —
 * additions require a paired backend PR (see the docstring above).
 */
export const ICON_WHITELIST = Object.freeze(Object.keys(ICON_MAP));


/** Resolve iconKey → component. Falls back to ExternalLink so a
 * stale pin from a retired icon still renders (rather than
 * crashing the entire rail). */
export function resolveIcon(iconKey) {
  return ICON_MAP[iconKey] || ExternalLink;
}
