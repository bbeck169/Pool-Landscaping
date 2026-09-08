/**
 * Feb-2026 · P0 defensive · schedule freeze mitigation.
 *
 * Tight error boundary around ``<ScheduleMap>``. Google Maps SDK
 * failures — most commonly ``BillingNotEnabledMapError`` (billing
 * disabled on the GCP project) or ``ApiNotActivatedMapError`` (key
 * rotation drops the Maps JS API scope) — surface as thrown
 * exceptions inside ``@vis.gl/react-google-maps``'s render path.
 *
 * Without a boundary, that throw bubbles up to the nearest React
 * error boundary. In ``CalendarSchedule`` there is NONE between the
 * ``<Map>`` and the top-level ``AppLayout`` boundary, so a Maps SDK
 * throw takes out the entire schedule day view — matching a
 * ``"the schedule freezes if any day has a job scheduled"`` user
 * report (map only renders when ``pins.length > 0``).
 *
 * This boundary keeps the throw local: the rest of the day view
 * (job cards, bulk actions, reorder controls) stays interactive.
 *
 * NOTE: this component intentionally has NO test dependencies on
 * ``@vis.gl/react-google-maps``; it is a pure React class error
 * boundary and can be tested standalone with a child that throws.
 */
import React from "react";

// Tenant-friendly fallback tile styling. Uses the same neutral
// gray as the schedule page's other "no-data" placeholders so it
// doesn't scream a stack trace at the operator.
const _FALLBACK_STYLE = {
  border: "1px solid #E5E7EB",
  background: "#F9FAFB",
  color: "#4B5563",
  height: 240,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 16,
  textAlign: "center",
  fontSize: 13,
  lineHeight: "20px",
};


export default class ScheduleMapErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { crashed: false, message: "" };
  }

  static getDerivedStateFromError(error) {
    // Extract just enough for the operator hint without leaking a
    // stack trace to the UI. The full error is still logged to the
    // console via ``componentDidCatch`` below.
    let msg = "";
    try {
      msg = String(error?.message || error || "").slice(0, 240);
    } catch {
      msg = "";
    }
    return { crashed: true, message: msg };
  }

  componentDidCatch(error, info) {
    // Console-only. No Sentry / no toast — a broken map is not a
    // pageable event, just a graceful degradation.
    // eslint-disable-next-line no-console
    console.warn(
      "[ScheduleMapErrorBoundary] Google Maps subtree crashed — " +
      "rendering fallback tile. Schedule cards below stay interactive.",
      { error, info },
    );
  }

  render() {
    if (this.state.crashed) {
      return (
        <div
          className="rounded-xl overflow-hidden mb-3"
          style={_FALLBACK_STYLE}
          data-testid="schedule-map-fallback"
          data-map-fallback-reason={this.state.message || "unknown"}
          role="alert"
          aria-label="Map temporarily unavailable"
        >
          <span>
            Map temporarily unavailable — check integration settings
            (Google Maps API key + billing).
          </span>
        </div>
      );
    }
    return this.props.children;
  }
}
