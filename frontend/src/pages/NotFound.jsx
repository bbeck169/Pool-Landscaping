import React from "react";
import { Link } from "react-router-dom";
import { colors } from "@/theme";

export default function NotFound({ code = 404, title, subtitle }) {
  const label = code === 500 ? "Something went wrong" : "Page not found";
  const detail = code === 500
    ? "The server hit an unexpected error. We're on it — try again in a moment."
    : "The page you're looking for doesn't exist or was moved.";
  return (
    <div className="min-h-screen flex items-center justify-center p-6"
         style={{ background: `linear-gradient(135deg, ${colors.brand}0F 0%, #fff 100%)` }}
         data-testid={`error-page-${code}`}>
      <div className="max-w-md w-full text-center rounded-3xl p-8 bg-white shadow-xl"
           style={{ border: `1px solid ${colors.border}` }}>
        <div className="text-6xl font-black" style={{ color: colors.brand }}>{code}</div>
        <div className="mt-2 text-xl font-bold" style={{ color: colors.onSurface }}>{title || label}</div>
        <div className="mt-2 text-sm" style={{ color: colors.onSurfaceSecondary }}>{subtitle || detail}</div>
        <div className="mt-6 flex gap-3 justify-center">
          <Link to="/" className="px-4 py-2 rounded-xl text-sm font-semibold text-white"
                style={{ backgroundColor: colors.brand }} data-testid="error-home-btn">
            Return home
          </Link>
          <button onClick={() => window.history.back()}
                  className="px-4 py-2 rounded-xl text-sm font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary }}
                  data-testid="error-back-btn">
            Go back
          </button>
        </div>
        <div className="mt-6 text-xs" style={{ color: colors.onSurfaceSecondary }}>
          Pool &amp; Landscaping of Vistancia
        </div>
      </div>
    </div>
  );
}

export function ErrorBoundary({ children }) {
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    const onErr = (e) => setErr(e.reason || e.error || e);
    window.addEventListener("unhandledrejection", onErr);
    window.addEventListener("error", onErr);
    return () => {
      window.removeEventListener("unhandledrejection", onErr);
      window.removeEventListener("error", onErr);
    };
  }, []);
  if (err) return <NotFound code={500} />;
  return children;
}
