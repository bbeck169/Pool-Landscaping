/**
 * LineItemsSection — Mobile parity for web LineItemsSection.jsx (F7).
 *
 * Full CRUD line-items editor on the job detail screen.
 * Admin: price, category, writeback, subtotals.
 * Tech: qty + description + notes only.
 * Online-only — shows offline banner when disconnected.
 */
import React, { useCallback, useState, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Modal,
  TextInput,
  Alert,
  ActivityIndicator,
  Switch,
  ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useAuth } from "@/src/auth";
import { useOnline } from "@/src/offline";
import { useToast } from "@/src/components/ToastProvider";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import {
  getLineItems,
  addLineItem,
  updateLineItem,
  deleteLineItem,
  getPricebookItems,
  getCategories,
  parseLineItemError,
} from "@/src/api/lineItems";
import type { LineItem, JobTotals, PricebookItem } from "@/src/api/lineItems";
import ChargeTemplatePickerModal from "./ChargeTemplatePickerModal";

const LOCKED = new Set(["completed", "cancelled"]);

/* ═══════════ Helpers ═══════════ */

function Skeleton() {
  return <View style={s.skeleton} />;
}

function CategoryChip({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable style={[s.catChip, selected && s.catChipActive]} onPress={onPress}>
      <Text style={[s.catChipText, selected && s.catChipTextActive]}>{label}</Text>
    </Pressable>
  );
}

/* ═══════════ Row ═══════════ */

function LIRow({
  item,
  isAdmin,
  locked,
  errInfo,
  onEdit,
  onDelete,
  disabled,
}: {
  item: LineItem;
  isAdmin: boolean;
  locked: boolean;
  errInfo?: { error_code: string; attempted_category?: string } | null;
  onEdit: () => void;
  onDelete: () => void;
  disabled?: boolean;
}) {
  const hasErr = !!errInfo;
  return (
    <Pressable
      style={[s.liRow, hasErr && s.liRowError]}
      onPress={locked || disabled ? undefined : onEdit}
      disabled={locked || disabled}
      testID={`job-lineitem-${item.id}`}
      accessibilityRole="button"
      accessibilityLabel={`Edit line item ${item.name || item.description || "Item"}`}
    >
      <View style={s.liRowMain}>
        <View style={{ flex: 1 }}>
          <Text style={s.liName} testID={`job-lineitem-${item.id}-name`}>
            {item.name || item.description || "Item"}
          </Text>
          <View style={s.liMeta}>
            <Text style={s.liMetaText}>Qty {item.quantity ?? 1}</Text>
            {item.category ? (
              <>
                <Text style={s.liMetaDot}>·</Text>
                <View style={s.liCatBadge}>
                  <Text style={s.liCatBadgeText}>{item.category}</Text>
                </View>
              </>
            ) : null}
          </View>
          {isAdmin && item.custom_price_override_flag ? (
            <Text style={s.customHint} testID={`job-lineitem-${item.id}-custom-hint`}>
              Custom price
            </Text>
          ) : null}
          {isAdmin && item.pricebook_writeback_flag ? (
            <Text style={s.wbHint} testID={`job-lineitem-${item.id}-writeback`}>
              ↳ Saves to pricebook
            </Text>
          ) : null}
          {hasErr ? (
            <Text style={s.rowErrText} testID={`job-lineitem-${item.id}-error`}>
              {errInfo!.error_code}
              {errInfo!.attempted_category ? ` — ${errInfo!.attempted_category}` : ""}
            </Text>
          ) : null}
        </View>
        {isAdmin && item.subtotal != null ? (
          <Text style={s.liTotal} testID={`job-lineitem-${item.id}-total`}>
            {money(item.subtotal)}
          </Text>
        ) : !isAdmin ? (
          <Text style={s.liNotes} numberOfLines={1}>
            {item.notes || "—"}
          </Text>
        ) : null}
      </View>
      {!locked && !disabled ? (
        <View style={s.liActions}>
          <Pressable
            style={s.liDeleteBtn}
            onPress={onDelete}
            hitSlop={8}
            testID={`job-lineitem-${item.id}-delete`}
            accessibilityLabel="Delete line item"
            accessibilityRole="button"
          >
            <Ionicons name="trash-outline" size={16} color={colors.error} />
          </Pressable>
          <Ionicons name="chevron-forward" size={14} color={colors.muted} />
        </View>
      ) : null}
    </Pressable>
  );
}

/* ═══════════ Add / Edit Sheet ═══════════ */

function AddEditSheet({
  jobId,
  visible,
  editItem,
  isAdmin,
  onClose,
  onDone,
  onRowError,
}: {
  jobId: string;
  visible: boolean;
  editItem: LineItem | null;
  isAdmin: boolean;
  onClose: () => void;
  onDone: (msg: string) => void;
  onRowError?: (liId: string, info: any) => void;
}) {
  const isEdit = !!editItem;

  const [desc, setDesc] = useState("");
  const [qty, setQty] = useState("1");
  const [unitPrice, setUnitPrice] = useState("");
  const [category, setCategory] = useState("");
  const [writeback, setWriteback] = useState(false);
  const [pbItemId, setPbItemId] = useState<string | null>(null);
  const [pbOrigPrice, setPbOrigPrice] = useState<number | null>(null);

  const [pbItems, setPbItems] = useState<PricebookItem[]>([]);
  const [pbSearch, setPbSearch] = useState("");
  const [pbLoading, setPbLoading] = useState(false);

  const [cats, setCats] = useState<{ id: string; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!visible) return;
    setErr("");
    if (isEdit && editItem) {
      setDesc(editItem.description || editItem.name || "");
      setQty(String(editItem.quantity ?? 1));
      setUnitPrice(String(editItem.unit_price ?? ""));
      setCategory(editItem.category || "");
      setWriteback(!!editItem.pricebook_writeback_flag);
      setPbItemId(editItem.pricebook_item_id || null);
      setPbOrigPrice(null);
    } else {
      setDesc("");
      setQty("1");
      setUnitPrice("");
      setCategory("");
      setWriteback(false);
      setPbItemId(null);
      setPbOrigPrice(null);
      setPbSearch("");
      loadPb("");
    }
    getCategories()
      .then((r) => setCats(r))
      .catch(() => setCats([]));
  }, [visible, editItem]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadPb = async (q: string) => {
    setPbLoading(true);
    try {
      const res = await getPricebookItems(q || undefined);
      setPbItems(res?.items || []);
    } catch {
      setPbItems([]);
    } finally {
      setPbLoading(false);
    }
  };

  useEffect(() => {
    if (isEdit || !visible) return;
    const t = setTimeout(() => loadPb(pbSearch), 300);
    return () => clearTimeout(t);
  }, [pbSearch, visible, isEdit]);

  const pickPbItem = (item: PricebookItem) => {
    setPbItemId(item.id);
    setDesc(item.name || "");
    if (isAdmin && item.unit_price != null) {
      setUnitPrice(String(item.unit_price));
      setPbOrigPrice(item.unit_price);
    }
    if (item.category) setCategory(item.category);
  };

  const priceChanged =
    pbOrigPrice != null && unitPrice !== "" && Number(unitPrice) !== pbOrigPrice;
  const canSubmit = (isEdit || desc.trim().length > 0) && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setErr("");
    try {
      if (isEdit) {
        const patch: any = { quantity: Number(qty) || 1 };
        if (isAdmin) {
          patch.unit_price = Number(unitPrice) || 0;
          patch.category = category || "";
          patch.pricebook_writeback = writeback;
        }
        await updateLineItem(jobId, editItem!.id, patch);
        onDone("Line item updated");
      } else {
        const body: any = {
          description: desc.trim(),
          quantity: Number(qty) || 1,
        };
        if (pbItemId) body.pricebook_item_id = pbItemId;
        if (isAdmin) {
          if (unitPrice !== "") body.unit_price = Number(unitPrice) || 0;
          body.category = category || "";
          body.pricebook_writeback = writeback;
        }
        await addLineItem(jobId, body);
        onDone("Line item added");
      }
    } catch (e: any) {
      const structured = parseLineItemError(e);
      if (structured?.error_code) {
        const msg = `${structured.error_code}${
          structured.attempted_category ? ` — ${structured.attempted_category}` : ""
        }`;
        setErr(msg);
        if (isEdit && editItem && onRowError) {
          onRowError(editItem.id, structured);
        }
      } else {
        setErr(e?.message || (isEdit ? "Update failed" : "Add failed"));
      }
    } finally {
      setBusy(false);
    }
  };

  const doDelete = () => {
    if (!isEdit || !editItem) return;
    Alert.alert(
      "Remove line item?",
      `Delete "${editItem.name || editItem.description || "Item"}"?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              await deleteLineItem(jobId, editItem.id);
              onDone("Line item removed");
            } catch (e: any) {
              setErr(e?.message || "Delete failed");
            } finally {
              setBusy(false);
            }
          },
        },
      ],
    );
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={s.sheetBg}>
        <View
          style={s.sheetCard}
          testID={isEdit ? "job-lineitem-edit-sheet" : "job-lineitem-add-sheet"}
        >
          <View style={s.sheetHandle} />
          <Text style={s.sheetTitle}>
            {isEdit ? "Edit line item" : "Add line item"}
          </Text>

          <ScrollView style={s.sheetBody} keyboardShouldPersistTaps="handled">
            {/* Pricebook picker (add mode only) */}
            {!isEdit ? (
              <View style={{ marginBottom: spacing.md }}>
                <Text style={s.fieldLabel}>From pricebook</Text>
                <View style={s.searchRow}>
                  <Ionicons name="search-outline" size={16} color={colors.muted} />
                  <TextInput
                    style={s.searchInput}
                    value={pbSearch}
                    onChangeText={setPbSearch}
                    placeholder="Search catalog…"
                    placeholderTextColor={colors.muted}
                    testID="job-lineitem-pb-search"
                  />
                </View>
                {pbLoading ? (
                  <ActivityIndicator
                    size="small"
                    color={colors.brand}
                    style={{ marginVertical: spacing.sm }}
                  />
                ) : pbItems.length === 0 ? (
                  <Text style={s.pbEmpty} testID="job-lineitem-pb-empty">
                    No items{pbSearch ? " for that search" : " in catalog"}.
                  </Text>
                ) : (
                  <View style={s.pbList}>
                    {pbItems.slice(0, 8).map((it) => (
                      <Pressable
                        key={it.id}
                        style={[s.pbItem, pbItemId === it.id && s.pbItemSelected]}
                        onPress={() => pickPbItem(it)}
                        testID={`job-lineitem-pb-item-${it.id}`}
                      >
                        <Ionicons name="cube-outline" size={14} color={colors.brand} />
                        <View style={{ flex: 1 }}>
                          <Text style={s.pbItemName}>{it.name}</Text>
                          <Text style={s.pbItemMeta}>
                            {it.category || it.unit || "—"}
                          </Text>
                        </View>
                        {isAdmin && it.unit_price != null ? (
                          <Text style={s.pbItemPrice}>{money(it.unit_price)}</Text>
                        ) : null}
                        {pbItemId === it.id ? (
                          <Ionicons
                            name="checkmark-circle"
                            size={16}
                            color={colors.brand}
                          />
                        ) : null}
                      </Pressable>
                    ))}
                  </View>
                )}
              </View>
            ) : null}

            {/* Description */}
            <Text style={s.fieldLabel}>Description</Text>
            <TextInput
              style={[s.input, isEdit && s.inputReadonly]}
              value={desc}
              onChangeText={isEdit ? undefined : setDesc}
              editable={!isEdit}
              placeholder="Item name or description"
              placeholderTextColor={colors.muted}
              testID="job-lineitem-desc"
            />

            {/* Quantity */}
            <Text style={[s.fieldLabel, { marginTop: spacing.md }]}>Quantity</Text>
            <TextInput
              style={s.input}
              value={qty}
              onChangeText={setQty}
              keyboardType="decimal-pad"
              testID="job-lineitem-qty"
            />

            {/* Unit Price (admin only) */}
            {isAdmin ? (
              <>
                <Text style={[s.fieldLabel, { marginTop: spacing.md }]}>
                  Unit price ($)
                </Text>
                <TextInput
                  style={s.input}
                  value={unitPrice}
                  onChangeText={setUnitPrice}
                  keyboardType="decimal-pad"
                  placeholder="0.00"
                  placeholderTextColor={colors.muted}
                  testID="job-lineitem-unit-price"
                />
                {priceChanged ? (
                  <Text
                    style={s.customPriceWarn}
                    testID="job-lineitem-custom-price-hint"
                  >
                    Custom price — pricebook shows {money(pbOrigPrice!)}
                  </Text>
                ) : null}
              </>
            ) : null}

            {/* Category (admin only) */}
            {isAdmin ? (
              <>
                <Text style={[s.fieldLabel, { marginTop: spacing.md }]}>Category</Text>
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  style={{ marginBottom: spacing.xs }}
                >
                  <CategoryChip
                    label="None"
                    selected={!category}
                    onPress={() => setCategory("")}
                  />
                  {cats.map((c) => (
                    <CategoryChip
                      key={c.id || c.name}
                      label={c.name}
                      selected={category === c.name}
                      onPress={() => setCategory(c.name)}
                    />
                  ))}
                </ScrollView>
                {cats.length === 0 ? (
                  <TextInput
                    style={s.input}
                    value={category}
                    onChangeText={setCategory}
                    placeholder="Enter category"
                    placeholderTextColor={colors.muted}
                    testID="job-lineitem-category-input"
                  />
                ) : null}
              </>
            ) : null}

            {/* Writeback toggle (admin only) */}
            {isAdmin ? (
              <View style={s.wbRow}>
                <Text style={s.wbLabel}>Also save to pricebook</Text>
                <Switch
                  value={writeback}
                  onValueChange={setWriteback}
                  trackColor={{ false: "#9CA3AF", true: colors.brand }}
                  testID="job-lineitem-writeback-toggle"
                />
              </View>
            ) : null}

            {err ? (
              <Text style={s.errText} testID="job-lineitem-sheet-error">
                {err}
              </Text>
            ) : null}
          </ScrollView>

          <View style={s.sheetFooter}>
            {isEdit ? (
              <Pressable
                style={s.deleteFooterBtn}
                onPress={doDelete}
                testID="job-lineitem-delete-btn"
              >
                <Ionicons name="trash-outline" size={16} color={colors.error} />
                <Text style={s.deleteFooterText}>Delete</Text>
              </Pressable>
            ) : null}
            <View style={{ flex: 1 }} />
            <Pressable
              style={s.ghostBtn}
              onPress={onClose}
              testID="job-lineitem-sheet-cancel"
            >
              <Text style={s.ghostBtnText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[s.primaryBtn, !canSubmit && s.btnDisabled]}
              onPress={submit}
              disabled={!canSubmit}
              testID="job-lineitem-sheet-submit"
              accessibilityRole="button"
              accessibilityLabel={isEdit ? "Save line item changes" : "Add line item"}
            >
              <Text style={s.primaryBtnText}>
                {busy
                  ? isEdit
                    ? "Saving…"
                    : "Adding…"
                  : isEdit
                    ? "Save changes"
                    : "Add item"}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/* ═══════════ Main Export ═══════════ */

type Props = { jobId: string; jobStatus?: string };

export default function LineItemsSection({ jobId, jobStatus }: Props) {
  const { showToast } = useToast();
  const { user } = useAuth();
  const online = useOnline();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const isTech = user?.role === "technician";
  const canView = isAdmin || isTech;
  const locked = LOCKED.has(jobStatus || "");

  const [items, setItems] = useState<LineItem[]>([]);
  const [totals, setTotals] = useState<JobTotals | null>(null);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [editItem, setEditItem] = useState<LineItem | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, any>>({});
  const [busyDel, setBusyDel] = useState<string | null>(null);
  const [templatePickerOpen, setTemplatePickerOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getLineItems(jobId);
      setItems(res?.line_items || []);
      setTotals(res?.job_totals || null);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    if (canView) load();
  }, [load, canView]);

  const handleDone = async (msg: string) => {
    setAddOpen(false);
    setEditItem(null);
    showToast(msg);
    await load();
  };

  const handleRowError = (liId: string, info: any) => {
    setRowErrors((prev) => ({ ...prev, [liId]: info }));
  };

  const handleDelete = (li: LineItem) => {
    Alert.alert(
      "Remove line item?",
      `Delete "${li.name || li.description || "Item"}"?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            setBusyDel(li.id);
            try {
              await deleteLineItem(jobId, li.id);
              showToast("Line item removed");
              await load();
            } catch (e: any) {
              Alert.alert("Error", e?.message || "Delete failed");
            } finally {
              setBusyDel(null);
            }
          },
        },
      ],
    );
  };

  if (!canView) return null;

  return (
    <View testID="job-line-items-section" style={s.container}>
      {/* Header */}
      <View style={s.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={s.sectionTitle} testID="job-line-items-title">
            Line Items
          </Text>
          <Text style={s.sectionSub}>
            {isAdmin
              ? "Add items from the pricebook. Totals refresh on every change."
              : "Add parts/materials used on this job."}
          </Text>
        </View>
        {!locked ? (
          <View style={s.headerBtns}>
            {isAdmin ? (
              <Pressable
                style={[s.templateBtn, !online && s.addBtnDisabled]}
                onPress={() => setTemplatePickerOpen(true)}
                disabled={!online}
                testID="job-lineitem-template-button"
                accessibilityLabel="Add from template"
                accessibilityRole="button"
              >
                <Ionicons name="layers-outline" size={14} color={colors.onSurface} />
                <Text style={s.templateBtnText}>Template</Text>
              </Pressable>
            ) : null}
            <Pressable
              style={[s.addBtn, !online && s.addBtnDisabled]}
              onPress={() => setAddOpen(true)}
              disabled={!online}
              testID="job-lineitem-add-button"
              accessibilityLabel="Add line item"
              accessibilityRole="button"
            >
              <Ionicons name="add" size={16} color="#fff" />
              <Text style={s.addBtnText}>Add line</Text>
            </Pressable>
          </View>
        ) : null}
      </View>

      {/* Offline banner */}
      {!online ? (
        <View style={s.offlineBanner} testID="job-lineitem-offline-banner">
          <Ionicons name="cloud-offline" size={14} color="#92400E" />
          <Text style={s.offlineText}>
            {"You're offline — line items require a connection"}
          </Text>
        </View>
      ) : null}

      {/* Content */}
      {loading ? (
        <View style={{ gap: spacing.sm }} testID="job-lineitem-loading">
          <Skeleton />
          <Skeleton />
        </View>
      ) : items.length === 0 ? (
        <View style={s.emptyWrap} testID="job-lineitem-empty">
          <Ionicons name="receipt-outline" size={28} color={colors.muted} />
          <Text style={s.emptyTitle}>No line items yet</Text>
          <Text style={s.emptySub}>
            {locked
              ? "This job is closed."
              : 'Tap "Add line" to add charges from the pricebook.'}
          </Text>
        </View>
      ) : (
        <View style={s.listWrap} testID="job-lineitem-list">
          {items.map((li) => (
            <LIRow
              key={li.id}
              item={li}
              isAdmin={isAdmin}
              locked={locked}
              errInfo={rowErrors[li.id]}
              onEdit={() => {
                setRowErrors((prev) => {
                  const c = { ...prev };
                  delete c[li.id];
                  return c;
                });
                setEditItem(li);
              }}
              onDelete={() => handleDelete(li)}
              disabled={!online || busyDel === li.id}
            />
          ))}

          {/* Totals (admin) */}
          {isAdmin && totals ? (
            <View style={s.totalsWrap} testID="job-lineitem-totals">
              <View style={s.totalRow}>
                <Text style={s.totalLabel}>Subtotal</Text>
                <Text style={s.totalValue} testID="job-lineitem-subtotal">
                  {money(totals.subtotal || 0)}
                </Text>
              </View>
              {totals.tax ? (
                <View style={s.totalRow}>
                  <Text style={s.totalLabel}>Tax</Text>
                  <Text style={s.totalValue}>{money(totals.tax)}</Text>
                </View>
              ) : null}
              <View style={[s.totalRow, s.totalRowFinal]}>
                <Text style={s.totalLabelBold}>TOTAL</Text>
                <Text style={s.totalValueBold} testID="job-lineitem-total">
                  {money(totals.total || 0)}
                </Text>
              </View>
            </View>
          ) : null}
        </View>
      )}

      {/* Charge Template Picker (admin only) */}
      {isAdmin ? (
        <ChargeTemplatePickerModal
          visible={templatePickerOpen}
          jobId={jobId}
          onClose={() => setTemplatePickerOpen(false)}
          onApplied={load}
        />
      ) : null}
      {/* Add Sheet */}
      <AddEditSheet
        jobId={jobId}
        visible={addOpen}
        editItem={null}
        isAdmin={isAdmin}
        onClose={() => setAddOpen(false)}
        onDone={handleDone}
      />
      {/* Edit Sheet */}
      <AddEditSheet
        jobId={jobId}
        visible={!!editItem}
        editItem={editItem}
        isAdmin={isAdmin}
        onClose={() => setEditItem(null)}
        onDone={handleDone}
        onRowError={handleRowError}
      />
    </View>
  );
}

/* ═══════════ Styles ═══════════ */

const s = StyleSheet.create({
  container: {
    marginVertical: spacing.md,
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  /* header */
  headerRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  headerBtns: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  sectionTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
  },
  sectionSub: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
  },
  addBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.brand,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
  },
  addBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
  addBtnDisabled: { opacity: 0.4 },
  templateBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
    borderWidth: 1,
    borderColor: colors.border,
  },
  templateBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  /* offline */
  offlineBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: "#FEF3C7",
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginBottom: spacing.md,
  },
  offlineText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#92400E",
    flex: 1,
  },
  /* skeleton */
  skeleton: {
    height: 56,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  /* empty */
  emptyWrap: {
    alignItems: "center",
    paddingVertical: spacing.xl,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
  },
  emptyTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginTop: spacing.sm,
  },
  emptySub: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 4,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
  },
  /* list + row */
  listWrap: { gap: spacing.sm },
  liRow: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    flexDirection: "row",
    alignItems: "center",
  },
  liRowError: { borderColor: colors.error, borderWidth: 2 },
  liRowMain: {
    flex: 1,
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
  },
  liName: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  liMeta: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 4,
    marginTop: 2,
  },
  liMetaText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  liMetaDot: { color: colors.muted, fontSize: 10 },
  liCatBadge: {
    backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.sm,
    paddingHorizontal: 6,
    paddingVertical: 1,
  },
  liCatBadgeText: {
    fontFamily: font.medium,
    fontSize: 10,
    color: colors.onSurfaceSecondary,
  },
  customHint: {
    fontFamily: font.medium,
    fontSize: 10,
    color: colors.warning,
    marginTop: 2,
  },
  wbHint: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.brand,
    marginTop: 1,
  },
  rowErrText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.error,
    marginTop: 4,
  },
  liTotal: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginLeft: spacing.sm,
  },
  liNotes: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    maxWidth: 120,
    marginLeft: spacing.sm,
  },
  liActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginLeft: spacing.sm,
  },
  liDeleteBtn: { padding: 4 },
  /* totals */
  totalsWrap: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
  },
  totalRow: {
    flexDirection: "row",
    justifyContent: "flex-end",
    alignItems: "center",
    gap: spacing.lg,
    paddingVertical: 2,
  },
  totalRowFinal: { marginTop: 4 },
  totalLabel: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  totalValue: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    minWidth: 60,
    textAlign: "right",
  },
  totalLabelBold: {
    fontFamily: font.bold,
    fontSize: 10,
    color: colors.muted,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  totalValueBold: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    minWidth: 60,
    textAlign: "right",
  },
  /* sheet */
  sheetBg: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "flex-end",
  },
  sheetCard: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingTop: spacing.sm,
    maxHeight: "85%",
  },
  sheetHandle: {
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.surfaceTertiary,
    alignSelf: "center",
    marginBottom: spacing.sm,
  },
  sheetTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  sheetBody: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  sheetFooter: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  /* form */
  fieldLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginBottom: 4,
  },
  input: {
    height: 42,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary,
  },
  inputReadonly: {
    backgroundColor: colors.surfaceTertiary,
    color: colors.muted,
  },
  searchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    marginBottom: spacing.sm,
  },
  searchInput: {
    flex: 1,
    height: 38,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  /* pricebook picker */
  pbEmpty: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    paddingVertical: spacing.md,
  },
  pbList: { gap: 2, marginBottom: spacing.sm },
  pbItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  pbItemSelected: { backgroundColor: "#EFF6FF" },
  pbItemName: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  pbItemMeta: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
  },
  pbItemPrice: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginRight: spacing.xs,
  },
  /* category chips */
  catChip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceTertiary,
    marginRight: spacing.xs,
  },
  catChipActive: { backgroundColor: colors.brand },
  catChipText: {
    fontFamily: font.medium,
    fontSize: 11,
    color: colors.onSurfaceSecondary,
  },
  catChipTextActive: { color: "#fff" },
  /* writeback */
  wbRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.md,
    paddingVertical: spacing.sm,
  },
  wbLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    flex: 1,
  },
  customPriceWarn: {
    fontFamily: font.medium,
    fontSize: 11,
    color: colors.warning,
    marginTop: 2,
  },
  errText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.error,
    marginTop: spacing.sm,
  },
  /* footer buttons */
  deleteFooterBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    borderRadius: radius.md,
  },
  deleteFooterText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.error,
  },
  ghostBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    borderRadius: radius.md,
  },
  ghostBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  primaryBtn: {
    backgroundColor: colors.brand,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    marginLeft: spacing.sm,
  },
  primaryBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
  btnDisabled: { opacity: 0.5 },
});
