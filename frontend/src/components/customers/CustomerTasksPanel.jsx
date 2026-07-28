import React, { useEffect, useState } from "react";
import { Plus, CheckCircle2, Circle, Clock, Trash2, User } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button, TextInput, EmptyState, Modal, Toast, Chip } from "@/components/ui-kit";
import { UserAvatar } from "@/components/UserAvatar";

/**
 * Customer Tasks panel — Feb-2026 Customer Detail Additions ship.
 *
 * Renders inside the CustomerDetail "Tasks" tab. Additionally exposes an
 * imperative ``openQuickAdd`` prop-callback via the ``registerOpener``
 * so the top-right "+ Create → To-Do" dropdown item can trigger the
 * quick-add modal directly without switching tabs.
 */
export function CustomerTasksPanel({ customerId, registerOpener }) {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [users, setUsers] = useState([]);
  const [toast, setToast] = useState(null);

  const [form, setForm] = useState({
    title: "",
    description: "",
    due_at: "",
    assigned_user_id: "",
    priority: "normal",
  });

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get(`/customer-tasks?customer_id=${customerId}`);
      setTasks(r || []);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    api.get("/team").then((r) => setUsers(r || [])).catch(() => {});
    if (registerOpener) registerOpener(() => setAddOpen(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  const submit = async () => {
    if (!form.title.trim()) {
      setToast({ tone: "error", message: "Title is required" });
      return;
    }
    try {
      await api.post("/customer-tasks", {
        customer_id: customerId,
        title: form.title.trim(),
        description: form.description.trim(),
        due_at: form.due_at || null,
        assigned_user_id: form.assigned_user_id || null,
        priority: form.priority,
      });
      setAddOpen(false);
      setForm({ title: "", description: "", due_at: "", assigned_user_id: "", priority: "normal" });
      setToast({ tone: "success", message: "Task created" });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const toggleComplete = async (t) => {
    try {
      if (t.status === "done") {
        await api.patch(`/customer-tasks/${t.id}`, { status: "open" });
      } else {
        await api.post(`/customer-tasks/${t.id}/complete`);
      }
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const remove = async (tid) => {
    try {
      await api.del(`/customer-tasks/${tid}`);
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  return (
    <div className="space-y-4" data-testid="customer-tasks-panel">
      <div className="flex justify-between items-center">
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          {tasks.length} task{tasks.length === 1 ? "" : "s"}
        </div>
        <Button onClick={() => setAddOpen(true)} testid="cd-tasks-new">
          <Plus size={14} /> New task
        </Button>
      </div>

      {loading ? null : tasks.length === 0 ? (
        <EmptyState
          title="No tasks yet"
          hint="Follow-ups, reminders, and to-dos related to this customer will appear here."
          action={<Button onClick={() => setAddOpen(true)}>Add first task</Button>}
        />
      ) : (
        <ul className="space-y-2" data-testid="cd-tasks-list">
          {tasks.map((t) => {
            const assignee = users.find((u) => u.id === t.assigned_user_id);
            return (
              <li
                key={t.id}
                className="flex items-start gap-3 p-3 rounded-xl"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}`,
                  opacity: t.status === "done" ? 0.6 : 1,
                }}
                data-testid={`cd-task-${t.id}`}
              >
                <button
                  onClick={() => toggleComplete(t)}
                  className="mt-0.5"
                  data-testid={`cd-task-toggle-${t.id}`}
                >
                  {t.status === "done" ? (
                    <CheckCircle2 size={20} color={colors.brand} />
                  ) : (
                    <Circle size={20} color={colors.muted} />
                  )}
                </button>
                <div className="flex-1 min-w-0">
                  <div
                    className="text-sm font-semibold"
                    style={{
                      color: colors.onSurface,
                      textDecoration: t.status === "done" ? "line-through" : "none",
                    }}
                  >
                    {t.title}
                  </div>
                  {t.description ? (
                    <div className="text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>
                      {t.description}
                    </div>
                  ) : null}
                  <div className="flex flex-wrap items-center gap-2 mt-2 text-xs" style={{ color: colors.muted }}>
                    {t.priority && t.priority !== "normal" ? (
                      <Chip
                        label={t.priority.toUpperCase()}
                        tone={t.priority === "high" ? "danger" : "muted"}
                      />
                    ) : null}
                    {t.due_at ? (
                      <span className="inline-flex items-center gap-1">
                        <Clock size={11} /> Due {new Date(t.due_at).toLocaleDateString()}
                      </span>
                    ) : null}
                    {assignee ? (
                      <span
                        className="inline-flex items-center gap-1"
                        data-testid={`cd-task-assignee-chip-${t.id}`}
                      >
                        <UserAvatar user={assignee} size="xs" />
                        {assignee.name}
                      </span>
                    ) : null}
                  </div>
                </div>
                <button
                  onClick={() => remove(t.id)}
                  data-testid={`cd-task-delete-${t.id}`}
                  className="opacity-60 hover:opacity-100"
                  title="Delete task"
                >
                  <Trash2 size={14} color={colors.danger} />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="New task"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button onClick={submit} testid="cd-task-submit">Create task</Button>
          </>
        }
      >
        <div className="space-y-3">
          <TextInput
            label="TITLE"
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            testid="cd-task-title"
          />
          <TextInput
            label="DESCRIPTION"
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            testid="cd-task-description"
          />
          <TextInput
            label="DUE DATE (optional)"
            type="date"
            value={form.due_at}
            onChange={(e) => setForm((f) => ({ ...f, due_at: e.target.value }))}
            testid="cd-task-due"
          />
          <div>
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>
              PRIORITY
            </div>
            <div className="flex gap-2">
              {["low", "normal", "high"].map((p) => (
                <button
                  key={p}
                  onClick={() => setForm((f) => ({ ...f, priority: p }))}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold uppercase transition"
                  style={{
                    backgroundColor:
                      form.priority === p ? colors.brand : colors.surfaceSecondary,
                    color: form.priority === p ? colors.onBrand : colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid={`cd-task-priority-${p}`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>
              ASSIGN TO (optional)
            </div>
            <select
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              value={form.assigned_user_id}
              onChange={(e) => setForm((f) => ({ ...f, assigned_user_id: e.target.value }))}
              data-testid="cd-task-assignee"
            >
              <option value="">— Unassigned —</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} ({u.role})
                </option>
              ))}
            </select>
          </div>
        </div>
      </Modal>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

export default CustomerTasksPanel;
