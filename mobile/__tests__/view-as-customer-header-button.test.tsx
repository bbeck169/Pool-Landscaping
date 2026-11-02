/**
 * A2 · profile header "View as customer" (ViewAsCustomerHeaderButton).
 * Gate matrix + tap → shared lib, rendered; screen wiring via source locks
 * (the 1.3k-line profile screen is not mounted — precedent td91 header test).
 */
import * as fs from "fs";
import * as path from "path";
import React from "react";
import { render, fireEvent, act } from "@testing-library/react-native";

const mockViewAs = jest.fn();
const mockToast = jest.fn();
jest.mock("@/src/lib/portalViewAsCustomer", () => ({ viewAsCustomer: (...a: any[]) => mockViewAs(...a) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));

// eslint-disable-next-line import/first
import ViewAsCustomerHeaderButton from "@/src/components/customers/ViewAsCustomerHeaderButton";

const SCREEN = fs.readFileSync(path.resolve(__dirname, "../app/customer/[id].tsx"), "utf8");
const ID = "customer-action-view-as-customer";
const mount = (p: Partial<React.ComponentProps<typeof ViewAsCustomerHeaderButton>> = {}) =>
  render(<ViewAsCustomerHeaderButton customerId="cust-1" role="admin" hasLogin active {...p} />);

beforeEach(() => { mockViewAs.mockReset().mockResolvedValue(undefined); mockToast.mockClear(); });

describe("A2 · header View as customer — gates (mirror PortalAccessPanel)", () => {
  it.each(["admin", "super_admin"])("%s + has login + active → enabled, labelled", (role) => {
    const q = mount({ role });
    const b = q.getByTestId(ID);
    expect(b.props.accessibilityLabel).toBe("View as customer");
    expect(b.props.accessibilityState).toEqual({ disabled: false, busy: false });
    expect(q.getByText("View as customer")).toBeTruthy();
  });
  it.each(["manager", "owner", "dispatcher", "technician", "customer", "", undefined, null])("role %p → hidden", (role) => {
    expect(mount({ role: role as any }).queryByTestId(ID)).toBeNull();
  });
  it("no login → hidden", () => {
    expect(mount({ hasLogin: false }).queryByTestId(ID)).toBeNull();
  });
  it("login revoked (!active) → disabled, tap does nothing", () => {
    const q = mount({ active: false });
    expect(q.getByTestId(ID).props.accessibilityState.disabled).toBe(true);
    fireEvent.press(q.getByTestId(ID));
    expect(mockViewAs).not.toHaveBeenCalled();
  });
});

describe("A2 · header View as customer — tap", () => {
  it("fires the shared viewAsCustomer with the customer id + setBusy/showToast deps", async () => {
    const q = mount({ customerId: "cust-42" });
    await act(async () => { fireEvent.press(q.getByTestId(ID)); });
    expect(mockViewAs).toHaveBeenCalledTimes(1);
    const [cid, deps] = mockViewAs.mock.calls[0];
    expect(cid).toBe("cust-42");
    expect(deps.showToast).toBe(mockToast);
    expect(typeof deps.setBusy).toBe("function");
  });
  it("busy while in flight → 'Opening…' + disabled; cleared after", async () => {
    let release: () => void = () => {};
    mockViewAs.mockImplementation((_id: string, d: any) => new Promise<void>((r) => {
      d.setBusy(true);
      release = () => { d.setBusy(false); r(); };
    }));
    const q = mount();
    await act(async () => { fireEvent.press(q.getByTestId(ID)); });
    expect(q.getByText("Opening…")).toBeTruthy();
    expect(q.getByTestId(ID).props.accessibilityState).toEqual({ disabled: true, busy: true });
    fireEvent.press(q.getByTestId(ID));
    expect(mockViewAs).toHaveBeenCalledTimes(1);
    await act(async () => { release(); });
    expect(q.getByText("View as customer")).toBeTruthy();
  });
});

describe("A2 · profile screen wiring (source locks)", () => {
  it("rendered in the header row right after 'Switch to customer view', steel sibling style", () => {
    const sw = SCREEN.indexOf('testID="impersonate-customer-button"');
    const va = SCREEN.indexOf("<ViewAsCustomerHeaderButton");
    const credit = SCREEN.indexOf('testID="customer-action-issue-credit"');
    expect(sw).toBeGreaterThan(0);
    expect(va).toBeGreaterThan(sw);
    expect(va).toBeLessThan(credit);
    const tag = SCREEN.slice(va, SCREEN.indexOf("/>", va));
    expect(tag).toContain("customerId={id as string}");
    expect(tag).toContain("role={user?.role}");
    expect(tag).toContain("hasLogin={portalStatus?.has_login ?? c.has_login ?? false}");
    expect(tag).toContain("active={portalStatus?.active ?? true}");
    expect(tag).toContain("style={[s2.actionBtn, s2.actionBtnSteel]}");
    expect(tag).toContain("textStyle={s2.actionBtnText}");
  });
  it("portal-status fetched for admin roles inside load() (panel onRefresh re-syncs it)", () => {
    const load = SCREEN.slice(SCREEN.indexOf("const load = useCallback(async () => {"), SCREEN.indexOf("useFocusEffect("));
    expect(load).toContain('const viewerRole = String(user?.role || "");');
    expect(load).toContain('if (viewerRole === "admin" || viewerRole === "super_admin") {');
    expect(load).toContain("api.get(`/customers/${id}/portal-status`)");
    expect(load).toContain(".catch(() => setPortalStatus(null));");
  });
  it("'Switch to customer view' unchanged (in-app session swap)", () => {
    expect(SCREEN).toContain('<Pressable style={[s2.actionBtn, s2.actionBtnSteel]} onPress={loginAsCustomer} disabled={impersonating} testID="impersonate-customer-button">');
    expect(SCREEN).toContain("const loginAsCustomer = () => setConfirmImp(true);");
    expect(SCREEN).toContain('await startImpersonation(id as string);');
    expect(SCREEN).toContain('router.replace("/portal/home");');
  });
});
